"""Xray versions across the cluster and one-click update (master now, nodes on their next poll)."""
import subprocess
import time

import httpx
from sqlalchemy import select

from . import config, settings_store
from .cores import run
from .db import Node, SessionLocal

_latest: dict = {"ts": 0, "tag": None}
INSTALL = 'bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install'


async def latest() -> str | None:
    if time.time() - _latest["ts"] > 3600:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
                r = await c.get("https://github.com/XTLS/Xray-core/releases/latest")
            _latest.update(ts=time.time(), tag=r.headers.get("location", "").rsplit("/", 1)[-1] or None)
        except httpx.HTTPError:
            pass
    return _latest["tag"]


async def versions() -> dict:
    _, out, _ = await run(config.XRAY_BIN, "version")
    with SessionLocal() as db:
        nodes = [{"name": n.name, "xray": (n.info or {}).get("xray", "")} for n in db.scalars(select(Node))]
    return {"master": out.split("\n")[0], "nodes": nodes, "latest": await latest()}


async def update_all() -> dict:
    """Updates Xray on the master (detached, the installer restarts xray) and asks nodes to update."""
    subprocess.Popen(["systemd-run", "--unit", f"nicro-xray-update-{int(time.time())}", "bash", "-c",
                      f"{INSTALL} && systemctl restart xray"])
    with SessionLocal() as db:
        s = settings_store.load(db)
        s["xray_update_seq"] = int(s.get("xray_update_seq", 0)) + 1
        settings_store.save(db, s)
    return {"ok": True, "message": "Обновляю Xray на главном сервере; серверы кластера обновятся в течение минуты"}
