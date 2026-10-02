"""L2TP/IPsec extension: per-client login/password for the VPN built into Windows, macOS, iOS and
Android — e.g. a separate tunnel for work next to the main key.

strongSwan (IKEv1, shared PSK) + xl2tpd; clients live in /etc/ppp/chap-secrets (written here from the
DB: only active users with L2TP enabled). ip-up/ip-down hooks record which user sits on which ppp
interface; traffic is counted from interface counters into the user's regular traffic, sessions of
users who lost access are hung up, and each session is a device for the one-device limit."""
import asyncio
import logging
import os
import re
import secrets
import signal
import subprocess
import time
from pathlib import Path

from . import settings_store
from .cores import run, systemctl
from .db import SessionLocal

log = logging.getLogger("vpnpanel.l2tp")
SESS = Path("/run/nicro-l2tp")
SUBNET = "10.66.0.0/24"
PACKAGES = ["strongswan", "strongswan-starter", "xl2tpd", "ppp"]
SERVICES = ["strongswan-starter", "xl2tpd"]
DEFAULTS = {"enabled": False, "psk": "", "dns": "1.1.1.1, 8.8.8.8"}

IP_UP = """#!/bin/sh
# nicro: remember which user sits on this ppp interface (PEERNAME) and their public IP (ipparam)
mkdir -p /run/nicro-l2tp
echo "$PEERNAME $6" > /run/nicro-l2tp/$1
"""
IP_DOWN = """#!/bin/sh
# nicro: final counters of the session for the panel's traffic accounting
[ -f /run/nicro-l2tp/$1 ] && echo "$(cut -d' ' -f1 /run/nicro-l2tp/$1) $BYTES_RCVD $BYTES_SENT" > /run/nicro-l2tp/final-$1-$(date +%s)
rm -f /run/nicro-l2tp/$1
"""


def settings() -> dict:
    with SessionLocal() as db:
        s = settings_store.load(db)
        cfg = {**DEFAULTS, **s.get("ext", {}).get("l2tp", {})}
        if not cfg["psk"]:
            cfg["psk"] = secrets.token_urlsafe(12)
            s.setdefault("ext", {})["l2tp"] = cfg
            settings_store.save(db, s)
    return cfg


def installed() -> bool:
    return Path("/usr/sbin/xl2tpd").exists() and Path("/usr/sbin/ipsec").exists()


def _wan() -> str:
    out = subprocess.run(["ip", "-4", "route", "show", "default"], capture_output=True, text=True).stdout
    m = re.search(r"dev (\S+)", out)
    return m.group(1) if m else "eth0"


def _write_configs(cfg: dict):
    Path("/etc/ipsec.conf").write_text(f"""# managed by nicro (Дополнения → L2TP)
config setup
    uniqueids=no

conn nicro-l2tp
    keyexchange=ikev1
    authby=secret
    type=transport
    left=%any
    leftprotoport=17/1701
    right=%any
    rightprotoport=17/%any
    ike=aes256-sha256-modp2048,aes256-sha1-modp2048,aes128-sha1-modp2048,aes256-sha1-modp1024,3des-sha1-modp1024!
    esp=aes256-sha256,aes256-sha1,aes128-sha1,3des-sha1!
    dpddelay=30
    dpdtimeout=120
    dpdaction=clear
    rekey=no
    auto=add
""")
    secrets_file = Path("/etc/ipsec.secrets")
    secrets_file.write_text(f'%any : PSK "{cfg["psk"]}"\n')
    secrets_file.chmod(0o600)
    Path("/etc/xl2tpd").mkdir(exist_ok=True)
    Path("/etc/xl2tpd/xl2tpd.conf").write_text("""; managed by nicro
[global]
port = 1701

[lns default]
ip range = 10.66.0.10-10.66.0.250
local ip = 10.66.0.1
require chap = yes
refuse pap = yes
require authentication = yes
name = nicro
pppoptfile = /etc/ppp/options.xl2tpd
length bit = yes
""")
    dns = "\n".join(f"ms-dns {d.strip()}" for d in cfg["dns"].split(",") if d.strip())
    Path("/etc/ppp/options.xl2tpd").write_text(f"""# managed by nicro
+mschap-v2
ipcp-accept-local
ipcp-accept-remote
noccp
auth
mtu 1280
mru 1280
proxyarp
lcp-echo-failure 4
lcp-echo-interval 30
connect-delay 5000
{dns}
""")
    for name, body in (("/etc/ppp/ip-up.d/nicro", IP_UP), ("/etc/ppp/ip-down.d/nicro", IP_DOWN)):
        Path(name).write_text(body)
        Path(name).chmod(0o755)


FW_RULES = [
    ("filter", "ufw-before-input", "-p udp -m multiport --dports 500,4500 -j ACCEPT"),
    ("filter", "ufw-before-input", "-p esp -j ACCEPT"),
    ("filter", "ufw-before-input", "-p udp --dport 1701 -m policy --dir in --pol ipsec -j ACCEPT"),
    ("filter", "ufw-before-forward", "-i ppp+ -j ACCEPT"),
    ("filter", "ufw-before-forward", "-o ppp+ -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"),
    ("nat", "POSTROUTING", f"-s {SUBNET} -o {{wan}} -j MASQUERADE"),
]


def ensure_firewall(on: bool):
    """Idempotent iptables rules next to ufw's chains (re-asserted periodically: ufw reloads drop them)."""
    wan = _wan()
    for table, chain, rule in FW_RULES:
        args = rule.format(wan=wan).split()
        exists = subprocess.run(["iptables", "-t", table, "-C", chain, *args], capture_output=True).returncode == 0
        if on and not exists:
            subprocess.run(["iptables", "-t", table, "-I" if table == "filter" else "-A", chain, *args], capture_output=True)
        elif not on and exists:
            subprocess.run(["iptables", "-t", table, "-D", chain, *args], capture_output=True)


async def install_and_enable() -> None:
    cfg = settings()
    if not installed():
        code, _, err = await run("bash", "-c", "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "
                                 + " ".join(PACKAGES), timeout=600)
        if code != 0:
            raise RuntimeError(f"установка пакетов не удалась: {err.strip()[-300:]}")
    _write_configs(cfg)
    ensure_firewall(True)
    for svc in SERVICES:
        await run("systemctl", "enable", svc)
        await systemctl("restart", svc)


async def disable() -> None:
    for svc in SERVICES:
        await run("systemctl", "disable", "--now", svc)
    ensure_firewall(False)
    hangup(lambda _u: True)


# ------------------------------------------------------------------ users, sessions, accounting

def write_secrets(creds: list[tuple[str, str]]):
    lines = ["# managed by nicro — L2TP clients (Дополнения → L2TP)"]
    lines += [f'"{u}" * "{p}" *' for u, p in creds]
    path = Path("/etc/ppp/chap-secrets")
    new = "\n".join(lines) + "\n"
    if not path.exists() or path.read_text() != new:
        path.write_text(new)
        path.chmod(0o600)


def sessions() -> dict[str, tuple[str, str]]:
    """ppp interface -> (username, client public IP)"""
    out = {}
    if SESS.exists():
        for f in SESS.iterdir():
            if f.name.startswith("ppp"):
                parts = f.read_text().split()
                if parts:
                    out[f.name] = (parts[0], parts[1] if len(parts) > 1 else "")
    return out


def hangup(should, iface: str | None = None):
    """Terminate pppd sessions whose user matches `should(username)` (or one interface)."""
    for ifc, (user, _) in sessions().items():
        if (iface and ifc != iface) or (not iface and not should(user)):
            continue
        pid_file = Path(f"/run/{ifc}.pid")
        try:
            os.kill(int(pid_file.read_text().split()[0]), signal.SIGTERM)
        except (OSError, ValueError):
            pass


class Accounting:
    def __init__(self):
        self.last: dict[str, tuple[int, int]] = {}  # iface -> (rx, tx) already counted

    def collect(self) -> dict[str, list[int]]:
        """{username: [up, down]} since the previous call, incl. sessions that just ended."""
        res: dict[str, list[int]] = {}

        def add(user, up, down):
            t = res.setdefault(user, [0, 0])
            t[0] += max(up, 0)
            t[1] += max(down, 0)
        live = sessions()
        for ifc, (user, _) in live.items():
            try:
                rx = int(Path(f"/sys/class/net/{ifc}/statistics/rx_bytes").read_text())
                tx = int(Path(f"/sys/class/net/{ifc}/statistics/tx_bytes").read_text())
            except (OSError, ValueError):
                continue
            prx, ptx = self.last.get(ifc, (0, 0))
            add(user, rx - prx, tx - ptx)  # rx at the server = client upload
            self.last[ifc] = (rx, tx)
        if SESS.exists():
            for f in SESS.glob("final-*"):
                parts = f.read_text().split()
                ifc = f.name.split("-")[1]
                if len(parts) == 3:
                    prx, ptx = self.last.pop(ifc, (0, 0))
                    add(parts[0], int(parts[1]) - prx, int(parts[2]) - ptx)
                f.unlink(missing_ok=True)
        for ifc in [i for i in self.last if i not in live]:
            self.last.pop(ifc, None)
        return {u: v for u, v in res.items() if v[0] or v[1]}


accounting = Accounting()


async def sync(users) -> None:
    """Called from the core sync: chap-secrets = active users with L2TP on; others are hung up."""
    if not settings()["enabled"] or not installed():
        return
    allowed = {u.username: u.l2tp_password for u in users if u.l2tp_enabled and u.l2tp_password}
    write_secrets(sorted(allowed.items()))
    hangup(lambda user: user not in allowed)


async def loop():
    from .cores.manager import manager
    n = 0
    while True:
        await asyncio.sleep(10)
        try:
            if not settings()["enabled"]:
                continue
            part = accounting.collect()
            if part:
                manager.add_traffic(part)
            n += 1
            if n % 6 == 0:
                ensure_firewall(True)
        except Exception:
            log.exception("l2tp loop failed")


def status() -> dict:
    cfg = settings()
    act = {}
    for svc in SERVICES:
        act[svc] = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True).stdout.strip()
    return {"enabled": cfg["enabled"], "installed": installed(), "services": act, "psk": cfg["psk"],
            "dns": cfg["dns"], "sessions": [{"iface": i, "user": u, "ip": ip} for i, (u, ip) in sessions().items()],
            "ts": int(time.time())}
