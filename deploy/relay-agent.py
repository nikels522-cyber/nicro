#!/usr/bin/env python3
"""Tiny metrics agent for a relay box (stdlib only). The panel polls GET /metrics with a bearer token."""
import hmac
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ["AGENT_TOKEN"]
MASTER = os.environ.get("MASTER", "").rstrip("/")  # panel URL: heartbeat so the panel follows IP changes
MACHINE_ID = open("/etc/machine-id").read().strip() if os.path.exists("/etc/machine-id") else ""
PORT = int(os.environ.get("AGENT_PORT", "9101"))
IFACE = os.environ.get("AGENT_IFACE", "eth0")
SSH_USER = os.environ.get("AGENT_SSH_USER", "root")  # whose authorized_keys the panel manages

state = {"cpu": 0.0, "rx_rate": 0.0, "tx_rate": 0.0}


def read(path: str, default: str = "") -> str:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


def cpu_times() -> tuple[int, int]:
    parts = [int(x) for x in read("/proc/stat").split("\n", 1)[0].split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    return idle, sum(parts)


def net_bytes() -> tuple[int, int]:
    for line in read("/proc/net/dev").splitlines():
        if line.strip().startswith(IFACE + ":"):
            f = line.split(":", 1)[1].split()
            return int(f[0]), int(f[8])
    return 0, 0


def sampler():
    idle0, total0 = cpu_times()
    rx0, tx0 = net_bytes()
    t0 = time.monotonic()
    while True:
        time.sleep(2)
        idle1, total1 = cpu_times()
        rx1, tx1 = net_bytes()
        t1 = time.monotonic()
        dt = max(t1 - t0, 1e-3)
        dtotal = max(total1 - total0, 1)
        state["cpu"] = round(100 * (1 - (idle1 - idle0) / dtotal), 1)
        state["rx_rate"] = max(rx1 - rx0, 0) / dt
        state["tx_rate"] = max(tx1 - tx0, 0) / dt
        idle0, total0, rx0, tx0, t0 = idle1, total1, rx1, tx1, t1


def snapshot() -> dict:
    mem = {}
    for line in read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        mem[k] = int(v.split()[0]) * 1024 if v.strip() else 0
    st = os.statvfs("/")
    rx, tx = net_bytes()
    temp = read("/sys/class/thermal/thermal_zone0/temp").strip()
    return {
        "ts": time.time(),
        "model": read("/proc/device-tree/model").strip("\x00\n ") or os.uname().machine,
        "hostname": os.uname().nodename,
        "cpu": state["cpu"],
        "cpu_count": os.cpu_count(),
        "load": [round(x, 2) for x in os.getloadavg()],
        "mem_total": mem.get("MemTotal", 0),
        "mem_used": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
        "disk_total": st.f_blocks * st.f_frsize,
        "disk_used": (st.f_blocks - st.f_bfree) * st.f_frsize,
        "temp": round(int(temp) / 1000, 1) if temp.isdigit() else None,
        "uptime": float(read("/proc/uptime", "0").split()[0]),
        "net_rx_rate": state["rx_rate"],
        "net_tx_rate": state["tx_rate"],
        "net_rx_total": rx,
        "net_tx_total": tx,
        "connections": int(read("/proc/sys/net/netfilter/nf_conntrack_count", "0").strip() or 0),
        "throttled": read("/sys/devices/platform/soc/soc:firmware/get_throttled").strip() or None,
        "machine_id": MACHINE_ID,
        "wan_ip": wan_ip(),
    }


PEER_PORTS = os.environ.get("AGENT_PEER_PORTS", "443 2083 2087 8443").split()


def peers() -> dict:
    """Clients with established connections to the relayed ports and ms since their last data
    (min over their sockets). Lets the panel count devices that are actually in use."""
    flt = " or ".join(f"sport = :{p}" for p in PEER_PORTS)
    try:
        out = subprocess.run(["ss", "-Htni", "state", "established", f"( {flt} )"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    result, ip = {}, None
    for line in out.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            cols = line.split()
            ip = cols[3].rsplit(":", 1)[0].strip("[]").removeprefix("::ffff:") if len(cols) >= 4 else None
            continue
        if ip:
            m = re.search(r"\blastrcv:(\d+)", line)
            ms = int(m.group(1)) if m else 10 ** 9
            result[ip] = min(ms, result.get(ip, 10 ** 9))
            ip = None
    return result


def wan_ip() -> str:
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", IFACE], capture_output=True, text=True,
                             timeout=5).stdout
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def heartbeat():
    """Tells the panel our current IP every minute (DHCP may change it; the panel updates the keys)."""
    import urllib.request
    registered = False
    while MASTER:
        try:
            body = json.dumps({"machine_id": MACHINE_ID, "ip": wan_ip(),
                               "name": os.environ.get("RELAY_NAME", "")}).encode()
            req = urllib.request.Request(f"{MASTER}/cluster/relay-heartbeat", data=body, method="POST",
                                         headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15).read()
            registered = True
        except Exception:
            pass
        time.sleep(60 if registered else 10)


def probe(targets: list[dict]) -> list[dict]:
    """Connects through every given VLESS outbound (panel's hidden probe identity) and checks that a
    small download passes. Uses the xray binary installed by relay-setup.sh (no service)."""
    import tempfile
    base = 31000
    cfg = {"log": {"loglevel": "none"},
           "inbounds": [{"port": base + i, "listen": "127.0.0.1", "protocol": "socks", "tag": f"i{i}"}
                        for i in range(len(targets))],
           "outbounds": [{**t["outbound"], "tag": f"o{i}"} for i, t in enumerate(targets)],
           "routing": {"rules": [{"type": "field", "inboundTag": [f"i{i}"], "outboundTag": f"o{i}"}
                                 for i in range(len(targets))]}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cfg, f)
    proc = subprocess.Popen(["/usr/local/bin/xray", "run", "-c", f.name], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    time.sleep(2)
    results = []
    try:
        for i, t in enumerate(targets):
            t0 = time.monotonic()
            r = subprocess.run(["curl", "-s", "-m", "15", "-x", f"socks5h://127.0.0.1:{base + i}", "-o", "/dev/null",
                                "-w", "%{http_code} %{size_download}", "https://speed.cloudflare.com/__down?bytes=200000"],
                               capture_output=True, text=True)
            ms = int((time.monotonic() - t0) * 1000)
            parts = r.stdout.split()
            ok = len(parts) == 2 and parts[0] == "200" and int(parts[1]) >= 200000
            results.append({"id": t["id"], "ok": ok, "ms": ms, "error": "" if ok else (r.stdout or "timeout")})
    finally:
        proc.kill()
        os.unlink(f.name)
    return results


ZAPRET = "/opt/nicro-zapret/nicro-zapret.sh"


def zapret(data: dict) -> dict:
    """DPI bypass (zapret) for this entry point's traffic to the main server: status / enable / select / disable.
    Selecting tests strategies for a minute or two, so it runs in the background; the panel polls the status."""
    if not os.path.exists(ZAPRET):
        return {"ok": False, "error": "на точке входа нет nicro-zapret.sh — обновите её (команда установки точки входа)"}
    action = data.get("action", "status")
    targets = ",".join(t for t in data.get("targets", []) if re.fullmatch(r"[A-Za-z0-9.-]+:\d+", t))
    if action in ("enable", "select"):
        subprocess.run(["systemctl", "stop", "nicro-zapret-job"], capture_output=True)
        steps = f"{ZAPRET} install; {ZAPRET} select {targets}" if action == "enable" else f"{ZAPRET} select {targets}"
        subprocess.run(["systemd-run", "--unit=nicro-zapret-job", "--collect", "bash", "-c", steps], capture_output=True)
    elif action == "disable":
        subprocess.run([ZAPRET, "disable"], capture_output=True, timeout=60)
    out = subprocess.run([ZAPRET, "status"], capture_output=True, text=True, timeout=30).stdout
    try:
        st = json.loads(out)
    except ValueError:
        return {"ok": False, "error": out[-300:] or "status failed"}
    st["busy"] = subprocess.run(["systemctl", "is-active", "--quiet", "nicro-zapret-job"]).returncode == 0
    return {"ok": True, "zapret": st}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        auth = self.headers.get("Authorization", "")
        if self.path not in ("/probe", "/ssh", "/zapret") or not hmac.compare_digest(auth, f"Bearer {TOKEN}"):
            self.send_error(404)
            return
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/ssh":  # SSH control from the panel (sshcore.py next to this agent)
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import sshcore
            body = json.dumps(sshcore.handle(data, SSH_USER)).encode()
        elif self.path == "/zapret":
            body = json.dumps(zapret(data)).encode()
        else:
            body = json.dumps(probe(data.get("targets", [])[:40])).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        if self.path not in ("/metrics", "/peers") or not hmac.compare_digest(auth, f"Bearer {TOKEN}"):
            self.send_error(404)
            return
        body = json.dumps(snapshot() if self.path == "/metrics" else peers()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    threading.Thread(target=sampler, daemon=True).start()
    threading.Thread(target=heartbeat, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
