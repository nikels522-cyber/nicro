"""System metrics sampler with an in-memory history ring buffer."""
import asyncio
import os
import time
from collections import deque

import psutil
from sqlalchemy.dialects.sqlite import insert

from .db import ServerDaily, SessionLocal, today


def _tcp_in_use() -> int:
    try:
        with open("/proc/net/sockstat") as f:
            for line in f:
                if line.startswith("TCP:"):
                    return int(line.split()[2])
    except OSError:
        pass
    return len(psutil.net_connections("tcp"))


class Monitor:
    def __init__(self):
        self.history: deque[dict] = deque(maxlen=450)  # 15 min at 2s
        self.latest: dict = {}
        self._net = psutil.net_io_counters()
        self._t = time.monotonic()
        self._pending_rx = 0
        self._pending_tx = 0
        psutil.cpu_percent(percpu=True)

    def sample(self) -> dict:
        now = time.monotonic()
        dt = max(now - self._t, 1e-3)
        net = psutil.net_io_counters()
        rx = max(net.bytes_recv - self._net.bytes_recv, 0)
        tx = max(net.bytes_sent - self._net.bytes_sent, 0)
        self._net, self._t = net, now
        self._pending_rx += rx
        self._pending_tx += tx

        cores = psutil.cpu_percent(percpu=True)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")
        load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
        snap = {
            "ts": time.time(),
            "cpu": round(sum(cores) / len(cores), 1),
            "cpu_cores": cores,
            "cpu_count": len(cores),
            "load": [round(x, 2) for x in load],
            "mem_used": mem.total - mem.available, "mem_total": mem.total,
            "swap_used": swap.used, "swap_total": swap.total,
            "disk_used": disk.used, "disk_total": disk.total,
            "net_rx_rate": rx / dt, "net_tx_rate": tx / dt,
            "net_rx_total": net.bytes_recv, "net_tx_total": net.bytes_sent,
            "tcp": _tcp_in_use(),
            "uptime": time.time() - psutil.boot_time(),
        }
        self.latest = snap
        self.history.append({k: snap[k] for k in ("ts", "cpu", "mem_used", "net_rx_rate", "net_tx_rate", "tcp")})
        return snap

    def flush_daily(self):
        rx, tx = self._pending_rx, self._pending_tx
        if not (rx or tx):
            return
        self._pending_rx = self._pending_tx = 0
        with SessionLocal() as db:
            stmt = insert(ServerDaily).values(day=today(), rx=rx, tx=tx)
            db.execute(stmt.on_conflict_do_update(
                index_elements=["day"], set_={"rx": ServerDaily.rx + rx, "tx": ServerDaily.tx + tx}))
            db.commit()

    async def loop(self, interval: int):
        n = 0
        while True:
            self.sample()
            n += 1
            if n % 30 == 0:
                await asyncio.to_thread(self.flush_daily)
            await asyncio.sleep(interval)


monitor = Monitor()
