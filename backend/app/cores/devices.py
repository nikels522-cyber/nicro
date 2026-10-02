"""Concurrent-device counting and the one-device limit (multi_device=False).

Units that can be "online":
  * a registered device — it fetched the subscription with a hardware ID and got its own Xray
    identity `<username>@d<id>`; counted exactly, even when several devices share one IP;
  * an address using the user's plain key (no hardware ID: raw vless:// link or an app that does
    not send x-hwid) — counted per client IP, the best that is possible without an identity.

A unit is online when one of its addresses is *in use right now*: within ACTIVE seconds it opened a
connection (Xray statsUserOnline timestamp) or received data on an established one (kernel lastrcv:
from `ss` here for direct clients, from the relay agent for clients behind a relay — relays pass
real IPs via PROXY protocol). Xray alone is not enough: it timestamps an IP only on new
connections and keeps dead connections of a phone that switched networks until they time out.

For limited users the owner unit keeps access; other online units are routed to the blackhole via
per-user routing rules added through the API (no restart). When the owner has been silent for
ACTIVE seconds (VPN off, switched network) the next online unit takes over."""
import asyncio
import ipaddress
import json
import re
import tempfile
import time
from pathlib import Path

from .. import config
from . import log, run
from .peers import local_peers

ACTIVE = 20  # seconds: an address is in use if it opened a connection or sent data this recently
POLL_INTERVAL = 3
DIRECT_PORT_KEYS = ("vless", "xhttp", "steal", "steal_xhttp")  # client-facing VLESS ports

# (username, multi_device, [device identity emails])
Identity = tuple[str, bool, list[str]]

ACCESS_LOG = Path("/var/log/xray/access.log")
ACCESS_LOG_MAX = 20 * 1024 * 1024  # truncate beyond this; we only need the tail
_ACCESS_RE = re.compile(r" from (?:tcp:|udp:)?\[?([0-9A-Fa-f.:]+?)\]?:\d+ accepted .*? email: (\S+)")


class AccessLogTail:
    """Follows Xray's access log: every new connection is logged instantly with its client IP and
    identity, so even sub-second connections (missed by polling statsonlineiplist) are seen."""

    def __init__(self):
        self.recent: dict[str, dict[str, int]] = {}  # email -> {ip: unix time of last new connection}
        self._pos = 0

    def seen(self, email: str, now: int) -> dict[str, int]:
        return {ip: t for ip, t in self.recent.get(email, {}).items() if now - t <= ACTIVE}

    def _read(self):
        try:
            size = ACCESS_LOG.stat().st_size
        except OSError:
            return
        if size < self._pos:  # truncated/rotated
            self._pos = 0
        if size > ACCESS_LOG_MAX:
            ACCESS_LOG.write_text("")  # xray appends, so truncating in place is safe
            self._pos = 0
            return
        with ACCESS_LOG.open("rb") as f:
            f.seek(self._pos)
            data = f.read()
            self._pos = f.tell()
        now = int(time.time())
        for line in data.decode(errors="replace").splitlines():
            m = _ACCESS_RE.search(line)
            if m:
                self.recent.setdefault(m.group(2), {})[m.group(1).removeprefix("::ffff:")] = now
        for email in list(self.recent):  # forget old entries
            self.recent[email] = {ip: t for ip, t in self.recent[email].items() if now - t <= ACTIVE * 3}
            if not self.recent[email]:
                del self.recent[email]

    async def loop(self):
        try:
            self._pos = ACCESS_LOG.stat().st_size  # start at the end
        except OSError:
            pass
        while True:
            try:
                self._read()
            except Exception:
                log.exception("access log tail failed")
            await asyncio.sleep(1)


access_log = AccessLogTail()


def _parse_ips(out: str) -> dict[str, int]:
    """statsonlineiplist output -> {ip: last_seen_unix}; tolerant to the exact JSON shape."""
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {}
    found: dict[str, int] = {}

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                try:
                    ipaddress.ip_address(k)
                    found[k] = int(v)
                    continue
                except (ValueError, TypeError):
                    pass
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return found


def load_identities() -> list[Identity]:
    from sqlalchemy import select

    from ..db import Device, SessionLocal, User, device_email, utcnow
    with SessionLocal() as db:
        now = utcnow()
        users = [u for u in db.scalars(select(User)) if u.status(now) == "active"]
        devs: dict[int, list[str]] = {}
        names = {u.id: u.username for u in users}
        for d in db.scalars(select(Device).where(Device.enabled, Device.user_id.in_(list(names)))):
            devs.setdefault(d.user_id, []).append(device_email(d.id, names[d.user_id]))
        return [(u.username, u.multi_device, devs.get(u.id, [])) for u in users]


def _relay_networks() -> list:
    """/16 networks of the entry points: a client on the same ISP reaches the relay with its internal
    (CGNAT) address and the main server directly with the ISP's public address."""
    import ipaddress
    from .. import settings_store
    from ..db import SessionLocal
    with SessionLocal() as db:
        relays = settings_store.load(db).get("relays", [])
    nets = []
    for r in relays:
        try:
            nets.append(ipaddress.ip_network(f"{r.get('host', '')}/16", strict=False))
        except ValueError:
            pass
    return nets


def group_ips(ips: dict[str, int], nets: list) -> list[tuple[list[str], int]]:
    """Plain-key addresses -> devices. One phone switching between a relay key and a direct key shows up
    as two addresses: its ISP-internal one at the relay (private/CGNAT) and the ISP's public one at the main
    server. Such pairs (private + public inside an entry point's /16) count as one device."""
    import ipaddress
    private, local, other = [], [], []
    for ip in ips:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            other.append(ip)
            continue
        if a.is_private or a in ipaddress.ip_network("100.64.0.0/10"):
            private.append(ip)
        elif any(a in n for n in nets):
            local.append(ip)
        else:
            other.append(ip)
    groups = [[ip] for ip in other]
    if private and local:
        # the internal address belongs to the most recently active public one; other homes stay separate
        best = max(local, key=lambda i: ips[i])
        groups.append([best] + sorted(private))
        groups += [[ip] for ip in local if ip != best]
    else:
        groups += [[ip] for ip in local + private]
    return [(g, max(ips[i] for i in g)) for g in groups]


class DeviceLimiter:
    def __init__(self):
        self.owner: dict[str, str] = {}  # username -> unit key holding access (limited users)
        self.applied: dict[str, tuple[frozenset[str], frozenset[str]]] = {}  # rule tag -> (users, sources)
        # username -> online units for the UI: {"key", "kind": "device"|"ip", "email"?, "ips", "last_seen", "blocked"}
        self.units: dict[str, list[dict]] = {}
        self._online: set[str] | None = None
        # rules every server must apply (tag -> rule), pulled by cluster nodes with their reports
        self.desired: dict[str, dict] = {}
        # cluster nodes' reports: callable -> {email: {ip: last_active_unix}}
        self.remote_online = lambda: {}
        self._remote: dict[str, dict[str, int]] = {}

    def reset(self):
        """Xray restarted: API-added rules are gone."""
        self.applied = {}

    def online_count(self, username: str) -> int:
        return sum(1 for x in self.units.get(username, []) if not x["blocked"])

    def device_online(self, email: str) -> dict | None:
        username = email.split("@d", 1)[0]
        return next((x for x in self.units.get(username, []) if x.get("email") == email), None)

    async def online_ips(self, email: str) -> dict[str, int]:
        from .xrayapi import stats
        try:  # gRPC: ~1 ms, no process (the CLI costs ~17 ms CPU and a 28 MB process per call)
            return await stats.online_ips(email)
        except Exception:
            code, out, _ = await run(config.XRAY_BIN, "api", "statsonlineiplist", f"--server={config.XRAY_API}",
                                     "-email", email)
            return _parse_ips(out) if code == 0 else {}

    async def live_peers(self) -> dict[str, int]:
        """{client_ip: ms since it last sent data} over direct clients and clients behind relays."""
        from .. import settings_store
        from ..db import SessionLocal
        from ..relays import relay_monitor
        with SessionLocal() as db:
            ports = settings_store.load(db)["ports"]
        live = await local_peers([ports[k] for k in DIRECT_PORT_KEYS if k in ports])
        for ip, ms in relay_monitor.all_peers().items():
            live[ip] = min(ms, live.get(ip, ms))
        return live

    async def online_emails(self) -> set[str] | None:
        """One cheap call listing identities Xray considers online; None if unavailable."""
        from .xrayapi import stats
        try:
            return await stats.online_users()
        except Exception:
            pass
        code, out, _ = await run(config.XRAY_BIN, "api", "statsgetallonlineusers", f"--server={config.XRAY_API}")
        if code != 0:
            return None
        return set(re.findall(r"user>>>(.+?)>>>online", out))

    async def _active_ips(self, email: str, live: dict[str, int], now: int, exact: bool = False) -> dict[str, int]:
        # The cheap "all online users" list misses identities between short connections; limited
        # users (exact=True) are always queried so a second device can't slip through.
        ips = access_log.seen(email, now)  # new connections, however short
        for ip, t in self._remote.get(email, {}).items():  # same identity active on a cluster node
            if now - t <= ACTIVE:
                ips[ip] = max(t, ips.get(ip, 0))
        if not exact and not ips and self._online is not None and email not in self._online:
            return {}
        for ip, opened in (await self.online_ips(email)).items():
            last = max(opened, now - live[ip] // 1000) if ip in live else opened
            if now - last <= ACTIVE:
                ips[ip] = max(last, ips.get(ip, 0))
        return ips

    async def _set_rule(self, tag: str, users: frozenset[str], sources: frozenset[str]):
        want = (users, sources) if users else None
        if want:
            self.desired[tag] = {"type": "field", "ruleTag": tag, "user": sorted(users), "outboundTag": "block",
                                 **({"source": sorted(sources)} if sources else {})}
        else:
            self.desired.pop(tag, None)
        if self.applied.get(tag) == want:
            return
        if tag in self.applied:
            await run(config.XRAY_BIN, "api", "rmrules", f"--server={config.XRAY_API}", tag)
            self.applied.pop(tag)
        if not want:
            return
        rule = {"type": "field", "ruleTag": tag, "user": sorted(users), "outboundTag": "block"}
        if sources:
            rule["source"] = sorted(sources)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"routing": {"rules": [rule]}}, f)
        try:
            code, out, err = await run(config.XRAY_BIN, "api", "adrules", f"--server={config.XRAY_API}",
                                       "-append", f.name)
        finally:
            Path(f.name).unlink(missing_ok=True)
        if code == 0:
            self.applied[tag] = want
        else:
            log.warning("device limit rule %s failed: %s %s", tag, out.strip(), err.strip())

    async def enforce(self, identities: list[Identity]):
        now = int(time.time())
        live = await self.live_peers()
        self._online = await self.online_emails()
        self._remote = self.remote_online()
        from .. import l2tp
        l2tp_sessions = l2tp.sessions()
        wanted_tags: set[str] = set()
        nets = _relay_networks()
        for username, multi, device_emails in identities:
            units: dict[str, dict] = {}
            for email in device_emails:
                ips = await self._active_ips(email, live, now, exact=not multi)
                if ips:
                    units[f"d:{email}"] = {"key": f"d:{email}", "kind": "device", "email": email,
                                           "ips": sorted(ips), "last_seen": max(ips.values())}
            for ips, last in group_ips(await self._active_ips(username, live, now, exact=not multi), nets):
                units[f"ip:{ips[0]}"] = {"key": f"ip:{ips[0]}", "kind": "ip", "ips": ips, "last_seen": last}
            for ifc, (user, ip) in l2tp_sessions.items():  # an L2TP/IPsec session is a device too
                if user == username:
                    units[f"l2tp:{ifc}"] = {"key": f"l2tp:{ifc}", "kind": "l2tp", "ips": [ip] if ip else [],
                                            "last_seen": now}

            blocked: set[str] = set()
            if not multi and units:
                owner = self.owner.get(username)
                if owner not in units:  # owner went quiet/changed network: the active unit takes over
                    owner = max(units, key=lambda k: units[k]["last_seen"])
                self.owner[username] = owner
                blocked = set(units) - {owner}
            else:
                self.owner.pop(username, None)
            for key, unit in units.items():
                unit["blocked"] = key in blocked
                if unit["blocked"] and unit["kind"] == "l2tp":
                    from .. import l2tp
                    l2tp.hangup(None, key.split(":", 1)[1])
            self.units[username] = sorted(units.values(), key=lambda x: -x["last_seen"])

            tag_dev, tag_ip = f"devlimit-{username}-dev", f"devlimit-{username}-ip"
            wanted_tags |= {tag_dev, tag_ip}
            await self._set_rule(tag_dev, frozenset(units[k]["email"] for k in blocked if k.startswith("d:")),
                                 frozenset())
            ip_blocked = frozenset(ip for k in blocked if k.startswith("ip:") for ip in units[k]["ips"])
            await self._set_rule(tag_ip, frozenset([username]) if ip_blocked else frozenset(), ip_blocked)

        known = {u for u, _, _ in identities}
        for tag in [t for t in self.applied if t not in wanted_tags]:  # deleted/disabled users
            await self._set_rule(tag, frozenset(), frozenset())
        for username in [u for u in self.units if u not in known]:
            self.units.pop(username, None)
            self.owner.pop(username, None)

    async def loop(self, lock):
        """Fast loop, separate from the 10s stats loop; shares the core lock with sync()."""
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                identities = load_identities()
                async with lock:
                    await self.enforce(identities)
            except Exception:
                log.exception("device limit iteration failed")


devices = DeviceLimiter()
