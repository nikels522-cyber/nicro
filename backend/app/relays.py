"""Polls metrics agents on relay boxes (deploy/relay-agent.py) and keeps the latest state."""
import asyncio
import time
from collections import deque

import httpx

from . import settings_store
from .db import SessionLocal

AGENT_PORT = 9101


class RelayMonitor:
    def __init__(self):
        self.state: dict[str, dict] = {}  # host -> status
        self.history: dict[str, deque] = {}
        self.peers: dict[str, dict[str, int]] = {}  # host -> {client_ip: ms since last data}

    def all_peers(self) -> dict[str, int]:
        merged: dict[str, int] = {}
        for p in self.peers.values():
            for ip, ms in p.items():
                merged[ip] = min(ms, merged.get(ip, ms))
        return merged

    async def _poll_peers(self, client: httpx.AsyncClient, relay: dict, token: str):
        try:
            r = await client.get(f"http://{relay['host']}:{AGENT_PORT}/peers",
                                 headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            self.peers[relay["host"]] = {k: int(v) for k, v in r.json().items()}
        except (httpx.HTTPError, ValueError):
            self.peers.pop(relay["host"], None)

    async def _poll(self, client: httpx.AsyncClient, relay: dict, token: str) -> dict:
        host = relay["host"]
        prev = self.state.get(host, {})
        t0 = time.monotonic()
        try:
            r = await client.get(f"http://{host}:{AGENT_PORT}/metrics", headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            m = r.json()
        except (httpx.HTTPError, ValueError) as e:
            return {**prev, "name": relay["name"], "host": host, "online": False,
                    "error": type(e).__name__, "checked_at": time.time()}
        rtt = round((time.monotonic() - t0) * 1000)
        hist = self.history.setdefault(host, deque(maxlen=180))  # 15 min at 5s
        hist.append({"ts": m["ts"], "cpu": m["cpu"], "rx": m["net_rx_rate"], "tx": m["net_tx_rate"],
                     "conn": m["connections"]})
        return {"name": relay["name"], "host": host, "online": True, "error": None, "rtt_ms": rtt,
                "checked_at": time.time(), "last_seen": time.time(), "metrics": m}

    async def poll_all(self):
        with SessionLocal() as db:
            s = settings_store.load(db)
        relays = [r for r in s.get("relays", []) if r.get("host")]
        if not hasattr(self, "_client"):  # kept between polls (every 3 s): no new connection pool / TLS context
            self._client = httpx.AsyncClient(timeout=4)
        client = self._client
        results = await asyncio.gather(*(self._poll(client, r, s["relay_token"]) for r in relays))
        await asyncio.gather(*(self._poll_peers(client, r, s["relay_token"]) for r in relays))
        self.state = {r["host"]: r for r in results}
        for host in set(self.peers) - {r["host"] for r in relays}:
            self.peers.pop(host, None)

    def summary(self) -> list[dict]:
        return list(self.state.values())

    def with_history(self) -> list[dict]:
        return [{**st, "history": list(self.history.get(host, []))} for host, st in self.state.items()]

    async def loop(self, interval: int = 3):
        while True:
            try:
                await self.poll_all()
            except Exception:  # never let monitoring kill the app
                pass
            await asyncio.sleep(interval)


relay_monitor = RelayMonitor()


# ------------------------------------------------------------------ relay IP changes (DHCP)

from fastapi import APIRouter, HTTPException, Request  # noqa: E402
from pydantic import BaseModel  # noqa: E402

public = APIRouter(prefix="/cluster")


class HeartbeatIn(BaseModel):
    machine_id: str
    ip: str
    name: str = ""  # RELAY_NAME from the installer: a new entry point registers itself under this name


async def regru_set_a(domain: str, ip: str, creds: dict) -> str:
    """Points `domain` to `ip` via the reg.ru API (the account must allow API access from this IP)."""
    import json as _json
    parts = domain.split(".")
    zone, sub = ".".join(parts[-2:]), ".".join(parts[:-2]) or "@"
    base = {"username": creds["username"], "password": creds["password"], "input_format": "json"}
    async with httpx.AsyncClient(timeout=20) as c:
        await c.post("https://api.reg.ru/api/regru2/zone/remove_record", data={**base, "input_data": _json.dumps(
            {"domains": [{"dname": zone}], "subdomain": sub, "record_type": "A"})})
        r = await c.post("https://api.reg.ru/api/regru2/zone/add_alias", data={**base, "input_data": _json.dumps(
            {"domains": [{"dname": zone}], "subdomain": sub, "ipaddr": ip})})
    res = r.json()
    if res.get("result") != "success":
        raise RuntimeError(res.get("error_text") or res.get("error_code") or "reg.ru error")
    return "ok"


@public.get("/relay-check")
def relay_check(request: Request):
    """The entry point installer verifies the token before changing anything."""
    with SessionLocal() as db:
        s = settings_store.load(db)
    if request.headers.get("authorization", "") != f"Bearer {s['relay_token']}":
        raise HTTPException(403)
    return {"ok": True}


@public.post("/relay-heartbeat")
async def relay_heartbeat(body: HeartbeatIn, request: Request):
    """The relay agent reports its current IP; when it changed, keys/links follow automatically."""
    with SessionLocal() as db:
        s = settings_store.load(db)
        if request.headers.get("authorization", "") != f"Bearer {s['relay_token']}" or not body.machine_id:
            raise HTTPException(404)
        import ipaddress
        from .auth import client_ip
        try:  # behind a home router the agent only knows its LAN address: use the one we see
            if ipaddress.ip_address(body.ip).is_private:
                body.ip = client_ip(request)
        except ValueError:
            body.ip = client_ip(request)
        changed = None
        added = None
        for r in s.get("relays", []):
            if r.get("machine_id") == body.machine_id or (not r.get("machine_id") and r.get("host") == body.ip):
                r["machine_id"] = body.machine_id
                if body.ip and r.get("host") != body.ip:
                    changed = (dict(r), r["host"])
                    r["host"] = body.ip
                break
        else:  # unknown machine with a valid token: a freshly installed entry point registers itself
            if body.ip and not any(r.get("host") == body.ip for r in s.get("relays", [])):
                name = (body.name.strip() or f"RU-{len(s.get('relays', [])) + 1}")[:32]
                added = {"name": name, "host": body.ip, "domain": "", "machine_id": body.machine_id}
                s.setdefault("relays", []).append(added)
        settings_store.save(db, s)
    if added:
        from .cores.manager import manager
        from .telegram import bot
        await manager.sync()  # PROXY-protocol twin inbounds appear for the first relay
        await bot.send_admins(f"🆕 <b>nicro:</b> подключена точка входа {added['name']} ({added['host']}). "
                              "Её ключи уже в подписках клиентов.")
        return {"ok": True, "registered": True}
    if changed:
        relay, old = changed
        note = f"IP точки входа {relay['name']} сменился: {old} → {body.ip}. Подписки обновлены автоматически."
        if relay.get("domain") and s.get("regru", {}).get("username"):
            try:
                await regru_set_a(relay["domain"], body.ip, s["regru"])
                note += f" DNS {relay['domain']} обновлён."
            except Exception as e:
                note += f" ⚠️ DNS {relay['domain']} обновить не удалось ({e}) — поменяйте A-запись вручную."
        elif relay.get("domain"):
            note += f" ⚠️ Поменяйте A-запись {relay['domain']} → {body.ip} (или укажите доступ к API reg.ru)."
        from .telegram import bot
        await bot.send_admins(f"🔄 <b>nicro:</b> {note}")
    return {"ok": True}
