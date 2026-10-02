"""Live TCP peers with the time since they last sent us data (Linux `ss -ti` lastrcv).

Used to tell whether a device is actually in use right now: Xray only timestamps an IP when it
opens a *new* connection, and keeps half-dead connections of a phone that switched networks
until they time out. Data flow is the reliable signal."""
import re

from . import run

_LASTRCV = re.compile(r"\blastrcv:(\d+)")


def _peer_ip(addr: str) -> str:
    host = addr.rsplit(":", 1)[0].strip("[]")
    return host.removeprefix("::ffff:")


def parse_ss(out: str) -> dict[str, int]:
    """`ss -Htni state established ...` -> {peer_ip: ms since last data received (min over sockets)}"""
    peers: dict[str, int] = {}
    ip = None
    for line in out.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():  # socket line: Recv-Q Send-Q Local Peer
            cols = line.split()
            ip = _peer_ip(cols[3]) if len(cols) >= 4 else None
            continue
        if ip is None:
            continue
        m = _LASTRCV.search(line)
        ms = int(m.group(1)) if m else 10 ** 9
        peers[ip] = min(ms, peers.get(ip, 10 ** 9))
        ip = None
    return peers


async def local_peers(ports: list[int]) -> dict[str, int]:
    if not ports:
        return {}
    flt = " or ".join(f"sport = :{p}" for p in ports)
    code, out, _ = await run("ss", "-Htni", "state", "established", f"( {flt} )")
    return parse_ss(out) if code == 0 else {}
