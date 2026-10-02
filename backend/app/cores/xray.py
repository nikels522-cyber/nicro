"""Xray-core: config generation, hot user add/remove via the gRPC API CLI, traffic stats."""
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .. import config
from . import log, run, systemctl

TAG_VLESS = "vless-reality"
TAG_XHTTP = "vless-xhttp"
TAG_SS = "ss2022"
TAG_STEAL = "vless-steal"  # REALITY camouflaged as our own site (see settings_store.steal_names)
TAG_STEAL_X = "vless-steal-xhttp"
# VLESS inbounds: (tag, protocol switch, port key, network, own-domain REALITY)
VLESS_SPECS = [
    (TAG_VLESS, "vless", "vless", "tcp", False),
    (TAG_XHTTP, "xhttp", "xhttp", "xhttp", False),
    (TAG_STEAL, "steal", "steal", "tcp", True),
    (TAG_STEAL_X, "steal", "steal_xhttp", "xhttp", True),
]
# Every VLESS inbound has a twin for traffic from relays: relays send PROXY protocol v2 so we see
# real client IPs (device counting / one-device limit). Relay port N -> here N + 10000.
RELAY_SUFFIX = "-relay"
RELAY_PORT_OFFSET = 10000
_SPEC_BY_TAG = {t: spec for spec in VLESS_SPECS for t in (spec[0], spec[0] + RELAY_SUFFIX)}


@dataclass(frozen=True)
class Creds:
    username: str
    uuid: str
    ss_key: str


def _client(tag: str, c: Creds) -> dict:
    spec = _SPEC_BY_TAG.get(tag)
    if spec is None:  # shadowsocks
        return {"password": c.ss_key, "email": c.username}
    if spec[3] == "tcp":
        return {"id": c.uuid, "email": c.username, "flow": "xtls-rprx-vision"}
    return {"id": c.uuid, "email": c.username}


def _reality(s: dict, steal: bool = False) -> dict:
    return {
        "show": False,
        "dest": config.STEAL_TARGET if steal else f"{s['reality_sni']}:443",
        "xver": 0,
        "serverNames": s["steal_names"] if steal else [s["reality_sni"]],
        "privateKey": s["reality_private"],
        "shortIds": [s["short_id"], ""],
    }


# routeOnly=False: connect to the sniffed domain instead of the requested IP. Clients with FakeIP
# (Hiddify/sing-box TUN) sometimes leak fake 198.18.0.0/15 addresses; this makes them work anyway.
# Clients on mobile networks often vanish without closing their connections (network switch, app killed);
# without TCP keepalive such connections stayed "established" for days — 13 000+ of them held ~300 MB of
# Xray memory. With keepalive a dead peer is detected and closed within ~3 minutes.
KEEPALIVE = {"tcpKeepAliveIdle": 60, "tcpKeepAliveInterval": 15}

SNIFF = {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": False}


def enabled_tags(s: dict) -> list[str]:
    p = s["protocols"]
    tags = []
    for tag, key, _, _, steal in VLESS_SPECS:
        if p.get(key) and (not steal or s.get("steal_names")):
            tags.append(tag)
            if s.get("relay_proxy"):
                tags.append(tag + RELAY_SUFFIX)
    if p.get("ss"):
        tags.append(TAG_SS)
    return tags


def _vless_inbound(s: dict, tag: str, users: list[Creds]) -> dict:
    _, _, port_key, network, steal = _SPEC_BY_TAG[tag]
    relay = tag.endswith(RELAY_SUFFIX)
    stream = {"network": network, "security": "reality", "realitySettings": _reality(s, steal)}
    if network == "xhttp":
        stream["xhttpSettings"] = {"path": s["xhttp_path"], "mode": "auto"}
    stream["sockopt"] = {**KEEPALIVE, **({"acceptProxyProtocol": True} if relay else {})}
    return {
        "tag": tag, "listen": "0.0.0.0", "port": s["ports"][port_key] + (RELAY_PORT_OFFSET if relay else 0),
        "protocol": "vless",
        "settings": {"clients": [_client(tag, u) for u in users], "decryption": "none"},
        "streamSettings": stream,
        "sniffing": SNIFF,
    }


def build_config(s: dict, users: list[Creds]) -> dict:
    tags = enabled_tags(s)
    inbounds = [_vless_inbound(s, t, users) for t in tags if t in _SPEC_BY_TAG]
    if TAG_SS in tags:
        inbounds.append({
            "tag": TAG_SS, "listen": "0.0.0.0", "port": s["ports"]["ss"], "protocol": "shadowsocks",
            "settings": {"method": s["ss_method"], "password": s["ss_server_key"],
                         "clients": [_client(TAG_SS, u) for u in users], "network": "tcp,udp"},
            "sniffing": SNIFF,
        })
    return _skeleton(inbounds, adblock=s.get("adblock", False), warp=s.get("warp"), speed=s.get("speed"))


ADBLOCK_RULE = {"type": "field", "domain": ["geosite:category-ads-all"], "outboundTag": "block"}


def _skeleton(inbounds: list[dict], api_listen: str = config.XRAY_API, adblock: bool = False,
              warp: dict | None = None, speed: dict | None = None) -> dict:
    from ..warp import outbound as warp_outbound, rule as warp_rule
    extra_out = [warp_outbound(warp["account"])] if warp else []
    # speed limits (speed.py): a marked copy of "direct" per limited user, shaped by tc on that mark
    speed_rules = []
    for mark, emails in (speed or {}).items():
        extra_out.append({"protocol": "freedom", "tag": f"direct-m{mark}", "settings": {"domainStrategy": "UseIPv4"},
                          "streamSettings": {"sockopt": {"mark": int(mark)}}})
        speed_rules.append({"type": "field", "user": emails, "outboundTag": f"direct-m{mark}"})
    return {
        # access log is tailed by cores/devices.py (per-connection events) and kept small there
        "log": {"loglevel": "warning", "access": "/var/log/xray/access.log"},
        "api": {"tag": "api", "listen": api_listen,
                "services": ["HandlerService", "StatsService", "LoggerService", "RoutingService"]},
        "stats": {},
        "policy": {
            "levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True, "statsUserOnline": True,
                             "handshake": 4, "connIdle": 300}},
            "system": {"statsInboundUplink": True, "statsInboundDownlink": True},
        },
        "inbounds": inbounds,
        "outbounds": [{"protocol": "freedom", "tag": "direct",
                       "settings": {"domainStrategy": "UseIPv4"}},
                      {"protocol": "blackhole", "tag": "block"}, *extra_out],
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": [
            {"type": "field", "ip": ["geoip:private"], "outboundTag": "block"},
            {"type": "field", "protocol": ["bittorrent"], "outboundTag": "block"},
            *([ADBLOCK_RULE] if adblock else []),
            *([warp_rule(warp["domains"])] if warp else []),
            *speed_rules,
        ]},
    }


def build_node_config(node: dict, xhttp_path: str, users: list[Creds], adblock: bool = False) -> dict:
    """Xray config for a cluster node (cluster.py): own-domain REALITY (Vision + XHTTP) with the
    node's own keys and domain; the camouflage site is the node's local Caddy on STEAL_TARGET."""
    reality = {"show": False, "dest": config.STEAL_TARGET, "xver": 0, "serverNames": [node["domain"]],
               "privateKey": node["reality_private"], "shortIds": [node["short_id"], ""]}
    inbounds = [
        {"tag": TAG_STEAL, "listen": "0.0.0.0", "port": node["ports"]["vision"], "protocol": "vless",
         "settings": {"clients": [_client(TAG_STEAL, u) for u in users], "decryption": "none"},
         "streamSettings": {"network": "tcp", "security": "reality", "realitySettings": reality, "sockopt": KEEPALIVE},
         "sniffing": SNIFF},
        {"tag": TAG_STEAL_X, "listen": "0.0.0.0", "port": node["ports"]["xhttp"], "protocol": "vless",
         "settings": {"clients": [_client(TAG_STEAL_X, u) for u in users], "decryption": "none"},
         "streamSettings": {"network": "xhttp", "xhttpSettings": {"path": xhttp_path, "mode": "auto"}, "sockopt": KEEPALIVE,
                            "security": "reality", "realitySettings": reality},
         "sniffing": SNIFF},
    ]
    return _skeleton(inbounds, "127.0.0.1:10085", adblock)


class Xray:
    def __init__(self):
        self.applied: dict[str, Creds] = {}
        self.applied_settings: dict | None = None

    def _write(self, s: dict, users: list[Creds]):
        config.XRAY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        tmp = config.XRAY_CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(build_config(s, users), indent=2))
        tmp.replace(config.XRAY_CONFIG)

    async def _api(self, cmd: str, *args: str) -> tuple[bool, str]:
        # flags must precede positional args (Go flag parsing stops at the first positional)
        code, out, err = await run(config.XRAY_BIN, "api", cmd, f"--server={config.XRAY_API}", *args)
        if code != 0:
            log.warning("xray api %s failed: %s %s", cmd, out.strip(), err.strip())
        return code == 0, out

    async def _hot_apply(self, s: dict, add: list[Creds], remove: list[str]) -> bool:
        if remove:
            for tag in enabled_tags(s):
                ok, _ = await self._api("rmu", f"-tag={tag}", *remove)
                if not ok:
                    return False
        if add:
            # adu needs complete inbound definitions; a partial one (tag+clients only) is
            # accepted with exit code 0 but silently adds nothing
            inbounds = build_config(s, add)["inbounds"]
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump({"inbounds": inbounds}, f)
            try:
                ok, out = await self._api("adu", f.name)
            finally:
                Path(f.name).unlink(missing_ok=True)
            added = re.search(r"Added (\d+) user", out)
            expected = len(add) * len(inbounds)
            if not ok or not added or int(added.group(1)) != expected:
                log.warning("xray adu added %s of %d users", added and added.group(1), expected)
                return False
        return True

    async def apply(self, s: dict, users: list[Creds], force_restart: bool = False):
        """Make the running Xray serve exactly `users`. Hot-patches via API when possible."""
        wanted = {u.username: u for u in users}
        self._write(s, users)
        restarted = False
        if force_restart or self.applied_settings != s:
            await systemctl("restart", config.XRAY_SERVICE)
            from .xrayapi import stats as grpc_stats
            await grpc_stats.reset()
            restarted = True
        else:
            remove = [n for n, c in self.applied.items() if wanted.get(n) != c]
            add = [c for n, c in wanted.items() if self.applied.get(n) != c]
            if (remove or add) and not await self._hot_apply(s, add, remove):
                log.warning("hot apply failed, restarting xray")
                await systemctl("restart", config.XRAY_SERVICE)
                restarted = True
        self.applied = wanted
        self.applied_settings = dict(s)
        return restarted

    async def pull_traffic(self) -> dict[str, list[int]]:
        """Per-user [up, down] bytes since the previous call (counters are reset)."""
        from .xrayapi import stats as grpc_stats
        try:  # one gRPC call instead of starting `xray api`
            stats = [{"name": k, "value": v} for k, v in (await grpc_stats.query("user>>>", reset=True)).items()]
        except Exception as e:
            log.debug("grpc statsquery failed (%s), using the CLI", e)
            code, out, _ = await run(config.XRAY_BIN, "api", "statsquery", f"--server={config.XRAY_API}",
                                     "-pattern", "user>>>", "-reset")
            if code != 0 or not out.strip():
                return {}
            try:
                stats = json.loads(out).get("stat", [])
            except json.JSONDecodeError:
                return {}
        result: dict[str, list[int]] = {}
        for st in stats:
            parts = st.get("name", "").split(">>>")
            if len(parts) != 4:
                continue
            value = int(st.get("value", 0) or 0)
            entry = result.setdefault(parts[1], [0, 0])
            entry[0 if parts[3] == "uplink" else 1] += value
        return result


xray = Xray()
