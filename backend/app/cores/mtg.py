"""Telegram MTProto proxies (mtg, Fake-TLS) fronted by our own domains.

One instance per entry point with an own domain: `mtg` (direct, :9443, steal_domain) and
`mtg-relay` (:9444, first relay's domain). Probes are fronted to the local camouflage site,
so the certificate always matches the SNI, like any normal HTTPS site."""
import hashlib
import hmac
from pathlib import Path

from .. import config
from . import run, systemctl

RELAY_CONFIG = Path("/etc/mtg-relay.toml")
RELAY_SERVICE = "mtg-relay"
RELAY_PORT = 9444
DIRECT_PORT = 9443

UNIT = """[Unit]
Description=Telegram MTProto proxy ({name})
After=network-online.target

[Service]
ExecStart=/usr/local/bin/mtg run {path}
DynamicUser=yes
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def secret_for(s: dict, domain: str) -> str:
    """Stable Fake-TLS secret: 'ee' + 16 key bytes + hex(domain)."""
    key = hmac.new(s["reality_private"].encode(), f"mtg:{domain}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"ee{key}{domain.encode().hex()}"


def instances(s: dict) -> list[dict]:
    out = []
    if s.get("steal_domain"):
        out.append({"service": config.MTG_SERVICE, "path": config.MTG_CONFIG, "port": DIRECT_PORT,
                    "domain": s["steal_domain"]})
    relay = next((r for r in s.get("relays", []) if r.get("domain")), None)
    if relay:
        out.append({"service": RELAY_SERVICE, "path": RELAY_CONFIG, "port": RELAY_PORT,
                    "domain": relay["domain"], "relay_host": relay["host"]})
    return out


def render(s: dict, inst: dict) -> str:
    fr_ip, fr_port = config.STEAL_TARGET.rsplit(":", 1)
    return (f'secret = "{secret_for(s, inst["domain"])}"\n'
            f'bind-to = "0.0.0.0:{inst["port"]}"\n'
            'prefer-ip = "prefer-ipv4"\n\n'
            '[domain-fronting]\n'
            f'ip = "{fr_ip}"\n'
            f'port = {fr_port}\n')


class Mtg:
    def __init__(self):
        self.applied: dict[str, str] = {}

    async def apply(self, s: dict):
        if not s.get("ext", {}).get("mtproto", {}).get("enabled", True):  # extension switched off
            if self.applied != {"off": "1"}:
                for svc in ("mtg", RELAY_SERVICE):
                    await run("systemctl", "disable", "--now", svc)
                self.applied = {"off": "1"}
            return
        force = bool(self.applied.get("off"))  # switched back on: start every instance again
        if force:
            self.applied = {}
        for inst in instances(s):
            text = render(s, inst)
            path: Path = inst["path"]
            if self.applied.get(inst["service"]) == text:
                continue
            if force:
                await run("systemctl", "enable", inst["service"])
            if force or not path.exists() or path.read_text() != text:
                path.write_text(text)
                path.chmod(0o644)
                unit = Path(f"/etc/systemd/system/{inst['service']}.service")
                if not unit.exists():
                    unit.write_text(UNIT.format(name=inst["service"], path=path))
                    await run("systemctl", "daemon-reload")
                    await systemctl("enable", inst["service"])
                await systemctl("restart", inst["service"])
            self.applied[inst["service"]] = text


mtg = Mtg()
