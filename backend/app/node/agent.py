#!/usr/bin/env python3
"""nicro cluster node agent (stdlib only). Runs on an extra exit server next to Xray.

Every INTERVAL seconds:
  * GET  {MASTER}/cluster/config  -> applies the Xray config (hot add/remove users via the Xray API
    when only users changed, restart otherwise);
  * POST {MASTER}/cluster/report  -> traffic deltas, devices online, metrics; applies the
    cluster-wide device-limit routing rules from the reply.
If the master is unreachable, Xray keeps serving the last applied config."""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.2"
MASTER = os.environ["MASTER"].rstrip("/")
SECRET = os.environ["SECRET"]
XRAY_BIN = os.environ.get("XRAY_BIN", "/usr/local/bin/xray")
XRAY_CONFIG = Path(os.environ.get("XRAY_CONFIG", "/usr/local/etc/xray/config.json"))
XRAY_SERVICE = os.environ.get("XRAY_SERVICE", "xray")
XRAY_API = os.environ.get("XRAY_API", "127.0.0.1:10085")
ACCESS_LOG = Path(os.environ.get("ACCESS_LOG", "/var/log/xray/access.log"))
INTERVAL = int(os.environ.get("INTERVAL", "5"))
ACTIVE = 20  # seconds: an address is in use if it opened a connection or sent data this recently
ACCESS_RE = re.compile(r" from (?:tcp:|udp:)?\[?([0-9A-Fa-f.:]+?)\]?:\d+ accepted .*? email: (\S+)")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def http(method: str, path: str, body=None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(MASTER + path, data=data, method=method, headers={
        "Authorization": f"Bearer {SECRET}", "Content-Type": "application/json", "User-Agent": f"nicro-node/{VERSION}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def xray_api(*args) -> tuple[int, str]:
    cmd = [XRAY_BIN, "api", args[0], f"--server={XRAY_API}", *args[1:]]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout + p.stderr


# Frequent stats questions go over gRPC when python3-grpcio is installed: `xray api` starts a 28 MB process
# per question (one per online client every few seconds). Minimal hand-written protobuf, no stubs.
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "false")
try:
    import grpc
except ImportError:
    grpc = None
_grpc_ch = None


def _pb_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _pb_fields(buf: bytes):
    i = 0
    while i < len(buf):
        key, i = _pb_read(buf, i)
        if key & 7 == 0:
            v, i = _pb_read(buf, i)
        elif key & 7 == 2:
            ln, i = _pb_read(buf, i)
            v, i = buf[i:i + ln], i + ln
        else:
            return
        yield key >> 3, v


def _pb_read(buf: bytes, i: int):
    n = shift = 0
    while True:
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7


def _grpc(method: str, req: bytes) -> bytes:
    global _grpc_ch
    if _grpc_ch is None:
        _grpc_ch = grpc.insecure_channel(XRAY_API)
    fn = _grpc_ch.unary_unary("/xray.app.stats.command.StatsService/" + method,
                              request_serializer=lambda b: b, response_deserializer=lambda b: b)
    return fn(req, timeout=5)


def online_users() -> set[str]:
    if grpc:
        try:
            return {v.decode().split(">>>")[1] for f, v in _pb_fields(_grpc("GetAllOnlineUsers", b"")) if f == 1}
        except Exception:
            pass
    _, out = xray_api("statsgetallonlineusers")
    return set(re.findall(r"user>>>(.+?)>>>online", out))


def online_ips(email: str) -> dict[str, int]:
    if grpc:
        name = f"user>>>{email}>>>online".encode()
        try:
            resp = _grpc("GetStatsOnlineIpList", _pb_varint(10) + _pb_varint(len(name)) + name)
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:  # no open connections
                return {}
            resp = None
        if resp is not None:
            out = {}
            for f, v in _pb_fields(resp):
                if f == 2:
                    kv = dict(_pb_fields(v))
                    if 1 in kv:
                        out[kv[1].decode()] = int(kv.get(2, 0))
            return out
    code, out = xray_api("statsonlineiplist", "-email", email)
    try:
        return {k: int(v) for k, v in (json.loads(out).get("ips", {}) if code == 0 else {}).items()}
    except ValueError:
        return {}


def xray_version() -> str:
    try:
        return subprocess.run([XRAY_BIN, "version"], capture_output=True, text=True, timeout=5).stdout.split("\n")[0]
    except (OSError, subprocess.SubprocessError):
        return ""


# ------------------------------------------------------------------ config apply

class ConfigApplier:
    def __init__(self):
        self.version = None
        self.current: dict | None = None
        try:
            self.current = json.loads(XRAY_CONFIG.read_text())
        except (OSError, ValueError):
            pass
        self.restarted = False  # tells RuleApplier its API rules are gone

    @staticmethod
    def _skeleton(cfg: dict) -> str:
        c = json.loads(json.dumps(cfg))
        for ib in c.get("inbounds", []):
            ib.get("settings", {}).pop("clients", None)
        return json.dumps(c, sort_keys=True)

    @staticmethod
    def _clients(cfg: dict) -> dict[str, dict[str, dict]]:
        return {ib["tag"]: {c["email"]: c for c in ib.get("settings", {}).get("clients", [])}
                for ib in cfg.get("inbounds", []) if "tag" in ib}

    def _write(self, cfg: dict):
        XRAY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        tmp = XRAY_CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        tmp.replace(XRAY_CONFIG)

    def _restart(self):
        subprocess.run(["systemctl", "restart", XRAY_SERVICE], timeout=30)
        self.restarted = True
        time.sleep(1.5)

    def _hot(self, old: dict, new: dict) -> bool:
        old_c, new_c = self._clients(old), self._clients(new)
        for tag, clients in new_c.items():
            before = old_c.get(tag, {})
            remove = [e for e, c in before.items() if clients.get(e) != c]
            add = [c for e, c in clients.items() if before.get(e) != c]
            if remove:
                code, out = xray_api("rmu", f"-tag={tag}", *remove)
                if code != 0:
                    return False
            if add:
                ib = next(i for i in new["inbounds"] if i.get("tag") == tag)
                ib = {**ib, "settings": {**ib["settings"], "clients": add}}
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                    json.dump({"inbounds": [ib]}, f)
                try:
                    code, out = xray_api("adu", f.name)
                finally:
                    os.unlink(f.name)
                m = re.search(r"Added (\d+) user", out)
                if code != 0 or not m or int(m.group(1)) != len(add):
                    return False
        return True

    def apply(self, payload: dict):
        if payload["version"] == self.version:
            return
        cfg = payload["xray"]
        cfg["api"]["listen"] = XRAY_API  # local overrides
        cfg["log"]["access"] = str(ACCESS_LOG)
        old = self.current
        self._write(cfg)
        if old is not None and self._skeleton(old) == self._skeleton(cfg) and self._hot(old, cfg):
            log("config: users updated live, version", payload["version"])
        else:
            self._restart()
            log("config: applied with xray restart, version", payload["version"])
        self.current, self.version = cfg, payload["version"]


# ------------------------------------------------------------------ device-limit rules

class RuleApplier:
    def __init__(self):
        self.applied: dict[str, str] = {}  # ruleTag -> json

    def apply(self, rules: list[dict], xray_restarted: bool):
        if xray_restarted:
            self.applied = {}
        want = {r["ruleTag"]: json.dumps(r, sort_keys=True) for r in rules}
        for tag in [t for t in self.applied if self.applied[t] != want.get(t)]:
            xray_api("rmrules", tag)
            self.applied.pop(tag)
        for tag, rj in want.items():
            if tag in self.applied:
                continue
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump({"routing": {"rules": [json.loads(rj)]}}, f)
            try:
                code, _ = xray_api("adrules", "-append", f.name)
            finally:
                os.unlink(f.name)
            if code == 0:
                self.applied[tag] = rj


# ------------------------------------------------------------------ activity

class Activity:
    """Which addresses of which identity are in use now: new connections (access log), open
    connections (Xray online list), data flow on established sockets (ss lastrcv)."""

    def __init__(self):
        self.recent: dict[str, dict[str, int]] = {}
        try:
            self.pos = ACCESS_LOG.stat().st_size
        except OSError:
            self.pos = 0

    def tail(self):
        try:
            size = ACCESS_LOG.stat().st_size
        except OSError:
            return
        if size < self.pos:
            self.pos = 0
        if size > 20 * 1024 * 1024:
            ACCESS_LOG.write_text("")
            self.pos = 0
            return
        with ACCESS_LOG.open("rb") as f:
            f.seek(self.pos)
            data = f.read()
            self.pos = f.tell()
        now = int(time.time())
        for line in data.decode(errors="replace").splitlines():
            m = ACCESS_RE.search(line)
            if m:
                self.recent.setdefault(m.group(2), {})[m.group(1).removeprefix("::ffff:")] = now
        for e in list(self.recent):
            self.recent[e] = {ip: t for ip, t in self.recent[e].items() if now - t <= ACTIVE * 3}
            if not self.recent[e]:
                del self.recent[e]

    @staticmethod
    def peers(ports: list[int]) -> dict[str, int]:
        if not ports:
            return {}
        flt = " or ".join(f"sport = :{p}" for p in ports)
        out = subprocess.run(["ss", "-Htni", "state", "established", f"( {flt} )"],
                             capture_output=True, text=True, timeout=10).stdout
        res, ip = {}, None
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
                res[ip] = min(ms, res.get(ip, 10 ** 9))
                ip = None
        return res

    def online(self, ports: list[int]) -> dict[str, dict[str, int]]:
        now = int(time.time())
        live = self.peers(ports)
        emails = online_users() | set(self.recent)
        result = {}
        for email in emails:
            ips = {ip: t for ip, t in self.recent.get(email, {}).items() if now - t <= ACTIVE}
            for ip, opened in online_ips(email).items():
                last = max(int(opened), now - live[ip] // 1000) if ip in live else int(opened)
                if now - last <= ACTIVE:
                    ips[ip] = max(last, ips.get(ip, 0))
            if ips:
                result[email] = ips
        return result


def traffic() -> dict[str, list[int]]:
    code, out = xray_api("statsquery", "-pattern", "user>>>", "-reset")
    res: dict[str, list[int]] = {}
    try:
        stats = json.loads(out).get("stat", []) if code == 0 else []
    except ValueError:
        return res
    for st in stats:
        parts = st.get("name", "").split(">>>")
        if len(parts) == 4:
            e = res.setdefault(parts[1], [0, 0])
            e[0 if parts[3] == "uplink" else 1] += int(st.get("value", 0) or 0)
    return {k: v for k, v in res.items() if v[0] or v[1]}


# ------------------------------------------------------------------ metrics

_m = {"cpu": 0.0, "rx": 0.0, "tx": 0.0}


def _sampler():
    def cpu():
        p = [int(x) for x in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]]
        return p[3] + p[4], sum(p)

    def net():
        rx = tx = 0
        for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
            name, rest = line.split(":", 1)
            if name.strip() != "lo":
                f = rest.split()
                rx, tx = rx + int(f[0]), tx + int(f[8])
        return rx, tx

    i0, t0 = cpu()
    r0, x0 = net()
    while True:
        time.sleep(3)
        i1, t1 = cpu()
        r1, x1 = net()
        _m["cpu"] = round(100 * (1 - (i1 - i0) / max(t1 - t0, 1)), 1)
        _m["rx"], _m["tx"] = (r1 - r0) / 3, (x1 - x0) / 3
        i0, t0, r0, x0 = i1, t1, r1, x1


def metrics() -> dict:
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, _, v = line.partition(":")
        mem[k] = int(v.split()[0]) * 1024 if v.strip() else 0
    st = os.statvfs("/")
    return {"cpu": _m["cpu"], "cpu_count": os.cpu_count(), "load": [round(x, 2) for x in os.getloadavg()],
            "mem_total": mem.get("MemTotal", 0), "mem_used": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
            "disk_total": st.f_blocks * st.f_frsize, "disk_used": (st.f_blocks - st.f_bfree) * st.f_frsize,
            "net_rx_rate": _m["rx"], "net_tx_rate": _m["tx"],
            "uptime": float(Path("/proc/uptime").read_text().split()[0])}


# ------------------------------------------------------------------ commands from the master

def run_command(cmd: dict) -> dict:
    """SSH control from the panel (sshcore.py is installed next to this agent)."""
    if "ssh" in cmd:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import sshcore
        except ImportError:
            return {"ok": False, "error": "на узле нет sshcore.py — переустановите агент"}
        return sshcore.handle(cmd["ssh"], "root")
    return {"ok": False, "error": "неизвестная команда"}


# ------------------------------------------------------------------ main loop

def main():
    threading.Thread(target=_sampler, daemon=True).start()
    cfg, rules, act = ConfigApplier(), RuleApplier(), Activity()
    xver = xray_version()
    log(f"nicro node agent {VERSION}, master {MASTER}, {xver}")
    pending: dict[str, list[int]] = {}  # traffic not yet delivered to the master
    update_seq = None  # "update Xray" requests from the master (panel button)
    done_cmd, cmd_result = None, None  # last command from the master and its result to report
    while True:
        try:
            payload = http("GET", "/cluster/config")
            seq = payload.get("xray_update", 0)
            if update_seq is not None and seq > update_seq:
                log("updating Xray on request of the master")
                subprocess.run(["bash", "-c", 'bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/'
                                'install-release.sh)" @ install'], timeout=600)
                cfg._restart()
                xver = xray_version()
            update_seq = seq
            cfg.apply(payload)
            cmd = payload.get("cmd") or {}
            if cmd.get("id") and cmd["id"] != done_cmd:
                done_cmd = cmd["id"]
                cmd_result = {"id": cmd["id"], "result": run_command(cmd)}
            act.tail()
            for e, (up, down) in traffic().items():
                p = pending.setdefault(e, [0, 0])
                p[0] += up
                p[1] += down
            ports = [ib["port"] for ib in (cfg.current or {}).get("inbounds", []) if "port" in ib]
            reply = http("POST", "/cluster/report", {"traffic": pending, "online": act.online(ports),
                                                     "metrics": metrics(), "agent": VERSION, "xray": xver,
                                                     "cmd_result": cmd_result})
            cmd_result = None
            pending = {}
            rules.apply(reply.get("rules", []), cfg.restarted)
            cfg.restarted = False
        except urllib.error.HTTPError as e:
            log("master rejected:", e.code, e.read()[:200])
            if e.code == 401:
                log("this node was removed from the cluster; stopping reports")
                time.sleep(60)
        except Exception as e:  # master unreachable etc.: keep serving the last config
            log("error:", type(e).__name__, e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
