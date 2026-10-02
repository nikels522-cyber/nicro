"""SSH management for every server of the cluster: on/off, password login on/off, keys.

The same code (node/sshcore.py) runs everywhere:
  main   — here, in a worker thread;
  r<i>   — relay i (e.g. the Raspberry Pi) through its agent: POST http://<relay>:9101/ssh (token auth);
  n<id>  — cluster node through the pull channel: the command rides on /cluster/config and the
           result comes back with the next /cluster/report (cluster.node_command)."""
import asyncio

import httpx

from . import settings_store
from .db import SessionLocal
from .node import sshcore


def servers() -> list[dict]:
    from .cluster import enabled_nodes, flag
    with SessionLocal() as db:
        s = settings_store.load(db)
    out = [{"id": "main", "name": settings_store.main_label(s), "kind": "main", "host": s["host"]}]
    out += [{"id": f"r{i}", "name": r["name"], "kind": "relay", "host": r["host"]}
            for i, r in enumerate(s.get("relays", [])) if r.get("host")]
    out += [{"id": f"n{n.id}", "name": f"{flag(n.country)} {n.name}", "kind": "node", "host": n.address}
            for n in enabled_nodes()]
    return out


async def call(server: str, cmd: dict) -> dict:
    """Runs an SSH action on `server`; returns {"state": ..., ["key"]} or raises RuntimeError."""
    if server == "main":
        res = await asyncio.to_thread(sshcore.handle, cmd, "root")
    elif server.startswith("r") and server[1:].isdigit():
        res = await _relay(int(server[1:]), cmd)
    elif server.startswith("n") and server[1:].isdigit():
        from .cluster import node_command
        res = await node_command(int(server[1:]), {"ssh": cmd})
    else:
        raise RuntimeError("Неизвестный сервер")
    if not res.get("ok"):
        raise RuntimeError(res.get("error") or "ошибка")
    return res


async def _relay(index: int, cmd: dict, path: str = "/ssh") -> dict:
    from .relays import AGENT_PORT
    with SessionLocal() as db:
        s = settings_store.load(db)
    relays = s.get("relays", [])
    if index >= len(relays) or not relays[index].get("host"):
        raise RuntimeError("Точка входа не найдена")
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.post(f"http://{relays[index]['host']}:{AGENT_PORT}{path}", json=cmd,
                             headers={"Authorization": f"Bearer {s['relay_token']}"})
    except httpx.HTTPError as e:
        raise RuntimeError(f"агент точки входа недоступен: {e}")
    if r.status_code == 404:
        raise RuntimeError("Агент на точке входа устарел — обновите его (relay-setup.sh)")
    return r.json()
