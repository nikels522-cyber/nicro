"""Hysteria2: config generation, HTTP-auth backed users, traffic stats API."""
import json
import shutil

import httpx

from .. import config
from . import log, systemctl


def hy_id(username: str, hy_password: str) -> str:
    """Connection id reported to hysteria. Includes a credential fingerprint because hysteria
    remembers kicks until the id's next packet: a recreated user or regenerated key must not
    inherit a stale kick."""
    return f"{username}.{hy_password[:6]}"


def username_of(hid: str) -> str:
    return hid.rsplit(".", 1)[0]


def build_config(s: dict) -> dict:
    cfg = {
        "listen": f":{s['ports']['hy']}",
        "tls": {"cert": str(config.HY_CERT), "key": str(config.HY_KEY)},
        "auth": {"type": "http", "http": {
            "url": f"http://127.0.0.1:{config.LISTEN_PORT}/internal/hy-auth/{config.INTERNAL_SECRET}",
            "insecure": False}},
        "trafficStats": {"listen": config.HY_STATS_LISTEN, "secret": s["hy_stats_secret"]},
        "masquerade": {"type": "proxy", "proxy": {"url": s["hy_masquerade"], "rewriteHost": True}},
        "ignoreClientBandwidth": False,
        # use the domain from TLS SNI / HTTP Host for IP-only requests (fixes leaked FakeIP addresses)
        "sniff": {"enable": True, "timeout": "2s", "rewriteDomain": False,
                  "tcpPorts": "80,443,8000-9000", "udpPorts": "all"},
        "quic": {"initStreamReceiveWindow": 8388608, "maxStreamReceiveWindow": 8388608,
                 "initConnReceiveWindow": 20971520, "maxConnReceiveWindow": 20971520},
    }
    if s["hy_obfs"]:
        cfg["obfs"] = {"type": "salamander", "salamander": {"password": s["hy_obfs_password"]}}
    return cfg


class Hysteria:
    def __init__(self):
        self.applied_settings: dict | None = None
        self.active: set[str] = set()

    def _client(self, s: dict) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=f"http://{config.HY_STATS_LISTEN}", timeout=5,
                                 headers={"Authorization": s["hy_stats_secret"]})

    async def apply(self, s: dict, active_users: set[str], force_restart: bool = False):
        """`active_users` are hy_id() values."""
        enabled = bool(s["protocols"].get("hy"))
        if force_restart or self.applied_settings != s:
            if config.HY_CONFIG.parent.exists():
                # YAML is a superset of JSON, so hysteria reads this file as-is
                config.HY_CONFIG.write_text(json.dumps(build_config(s), indent=2))
                try:  # hysteria runs as its own user and must be able to read the config
                    shutil.chown(config.HY_CONFIG, "root", "hysteria")
                    config.HY_CONFIG.chmod(0o640)
                except (LookupError, OSError):
                    pass
                await systemctl("restart" if enabled else "stop", config.HY_SERVICE)
            self.applied_settings = dict(s)
        # Users that lost access get kicked; new connections are rejected by the auth hook
        kicked = self.active - active_users
        if kicked and enabled:
            try:
                async with self._client(s) as c:
                    await c.post("/kick", json=sorted(kicked))
            except httpx.HTTPError as e:
                log.warning("hysteria kick failed: %s", e)
        self.active = set(active_users)

    async def pull_traffic(self, s: dict) -> dict[str, list[int]]:
        if not s["protocols"].get("hy"):
            return {}
        try:
            async with self._client(s) as c:
                r = await c.get("/traffic", params={"clear": "1"})
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError):
            return {}
        # hysteria reports tx/rx from the client's point of view: tx = upload, rx = download
        result: dict[str, list[int]] = {}
        for hid, v in data.items():
            entry = result.setdefault(username_of(hid), [0, 0])
            entry[0] += int(v.get("tx", 0))
            entry[1] += int(v.get("rx", 0))
        return result

    async def online(self, s: dict) -> dict[str, int]:
        if not s["protocols"].get("hy"):
            return {}
        try:
            async with self._client(s) as c:
                r = await c.get("/online")
                return r.json() if r.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return {}


hysteria = Hysteria()
