"""Closes VPN connections that carry nothing.

XHTTP clients open a new TCP connection for many requests and keep the old ones in their pool; Xray never
closes an idle XHTTP connection and has no option for it. On a live server that grew to 8 000+ connections
(thousands per client) — Xray took ~300 MB and a large share of the CPU. TCP keepalive doesn't help: the
peers are alive and answer. Once a minute, connections on the VPN ports with no data in either direction for
IDLE seconds are destroyed (ss -K); a client that still needs one simply opens a new connection. Xray itself
treats a proxied flow idle for 300 s as finished (policy connIdle), so nothing in use is cut."""
import asyncio
import re

from .. import settings_store
from ..db import SessionLocal
from . import log, run

IDLE = 300  # seconds without data both ways
INTERVAL = 60
BATCH = 80  # sockets per ss -K call
_SOCK = re.compile(r"^\d+\s+\d+\s+(\S+):(\d+)\s+(\S+):(\d+)")


def _ports() -> list[int]:
    with SessionLocal() as db:
        p = settings_store.load(db)["ports"]
    base = {p.get(k) for k in ("vless", "xhttp", "steal", "steal_xhttp") if p.get(k)}
    return sorted(base | {x + 10000 for x in base})  # + PROXY-protocol twins for entry points


async def reap_once() -> int:
    ports = _ports()
    flt = "( " + " or ".join(f"sport = :{p}" for p in ports) + " )"
    code, out, _ = await run("ss", "-Htni", "state", "established", flt)
    if code != 0:
        return 0
    idle, cur = [], None
    for line in out.split("\n"):
        m = _SOCK.match(line)
        if m:
            cur = m.groups()
            continue
        if cur is None:
            continue
        rcv, snd = re.search(r"lastrcv:(\d+)", line), re.search(r"lastsnd:(\d+)", line)
        if rcv and snd and int(rcv.group(1)) > IDLE * 1000 and int(snd.group(1)) > IDLE * 1000:
            idle.append(f"( dst {cur[2]}:{cur[3]} and sport = :{cur[1]} )")
        cur = None
    for i in range(0, len(idle), BATCH):
        await run("ss", "-K", "state", "established", " or ".join(idle[i:i + BATCH]))
    return len(idle)


async def loop():
    await asyncio.sleep(90)
    while True:
        try:
            n = await reap_once()
            if n:
                log.info("closed %d idle VPN connections", n)
        except Exception:
            log.exception("idle connection cleanup failed")
        await asyncio.sleep(INTERVAL)
