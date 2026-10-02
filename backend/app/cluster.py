"""nicro cluster: extra exit servers (nodes) joined to this master by a one-time token.

Flow
  1. Admin clicks "Add server" -> one-time join token (1 h) + install command.
  2. The node's installer calls POST /cluster/join with the token -> the node gets its id and a
     long-lived secret (only its SHA-256 is stored here), its own REALITY keys and domain.
  3. The node agent (node/agent.py) every few seconds:
       GET  /cluster/config  -> Xray config with all active users (+ version hash)
       POST /cluster/report  -> traffic deltas, online devices, metrics; reply = device-limit rules
Pull-based: nodes need no open management port, and keep serving the last config if the master
is unreachable. Traffic is summed over all servers and the one-device limit is cluster-wide."""
import asyncio
import hashlib
import json
import re
import secrets
import time
from datetime import timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select

from . import auth, settings_store
from .cores.devices import devices
from .cores.manager import manager
from .cores.xray import build_node_config
from .db import JoinToken, Node, SessionLocal, utcnow

NODE_FILES = Path(__file__).parent / "node"
REPORT_TTL = 20  # seconds: a node's online data counts while its last report is this fresh
ONLINE_AFTER = 30  # seconds without a report -> node shown offline
DEFAULT_PORTS = {"vision": 443, "xhttp": 8443}

public = APIRouter(prefix="/cluster")  # used by nodes (token/secret auth), outside the panel path
admin = APIRouter()  # panel API (admin auth)

_reports: dict[int, tuple[float, dict]] = {}  # node id -> (time, {email: {ip: last_active}})
_commands: dict[int, dict] = {}  # node id -> pending command, delivered with /cluster/config
_results: dict[str, dict] = {}  # command id -> result from /cluster/report


async def node_command(node_id: int, cmd: dict, timeout: float = 30) -> dict:
    """Runs `cmd` on a node (e.g. {\"ssh\": {...}}, see node/sshcore.py) and waits for the result."""
    with SessionLocal() as db:
        if not db.get(Node, node_id):
            raise RuntimeError("Узел не найден")
    cid = secrets.token_hex(8)
    _commands[node_id] = {**cmd, "id": cid}
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cid in _results:
            return _results.pop(cid)
        await asyncio.sleep(0.5)
    if _commands.get(node_id, {}).get("id") == cid:
        _commands.pop(node_id)
    raise RuntimeError("Узел не ответил — проверьте, что он онлайн и агент обновлён")


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def flag(country: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country.upper()) if len(country) == 2 else "🌐"


def remote_online() -> dict[str, dict[str, int]]:
    """Merged online devices reported by live nodes (plugged into cores/devices.py)."""
    now = time.time()
    merged: dict[str, dict[str, int]] = {}
    for t, online in _reports.values():
        if now - t > REPORT_TTL:
            continue
        for email, ips in online.items():
            dst = merged.setdefault(email, {})
            for ip, ts in ips.items():
                dst[ip] = max(int(ts), dst.get(ip, 0))
    return merged


devices.remote_online = remote_online


def enabled_nodes() -> list[Node]:
    with SessionLocal() as db:
        return list(db.scalars(select(Node).where(Node.enabled).order_by(Node.id)))


# ---------------------------------------------------------------- node-facing endpoints

def node_auth(request: Request) -> Node:
    header = request.headers.get("authorization", "")
    secret = header.removeprefix("Bearer ").strip()
    with SessionLocal() as db:
        node = db.scalar(select(Node).where(Node.secret_hash == _hash(secret))) if secret else None
    if not node:
        raise HTTPException(401, "unknown node")
    return node


class JoinIn(BaseModel):
    token: str
    ip: str
    hostname: str = ""
    domain: str = ""  # optional own domain; default <ip>.sslip.io
    ports: dict | None = None  # optional port overrides (tests / non-standard setups)


async def _country(ip: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"https://ipinfo.io/{ip}/country")
            code = r.text.strip()
            return code if re.fullmatch(r"[A-Z]{2}", code) else ""
    except httpx.HTTPError:
        return ""


@public.post("/join")
async def join(body: JoinIn):
    if not re.fullmatch(r"[0-9a-fA-F.:]{3,45}", body.ip):
        raise HTTPException(400, "bad ip")
    with SessionLocal() as db:
        tok = db.scalar(select(JoinToken).where(JoinToken.token_hash == _hash(body.token.strip())))
        if not tok or tok.used or tok.expires_at < utcnow():
            raise HTTPException(403, "Токен недействителен или истёк — создайте новый в панели")
        tok.used = True
        db.commit()
        name, domain = tok.name, (body.domain or tok.domain).strip().lower()
    domain = domain or f"{body.ip.replace('.', '-')}.sslip.io"
    priv, pub = settings_store.gen_reality_keys()
    secret = "nkl_node_" + secrets.token_urlsafe(32)
    ports = {**DEFAULT_PORTS, **{k: int(v) for k, v in (body.ports or {}).items() if k in DEFAULT_PORTS}}
    node = Node(name=name, address=body.ip, domain=domain, country=await _country(body.ip),
                secret_hash=_hash(secret), reality_private=priv, reality_public=pub,
                short_id=secrets.token_hex(8), ports=ports, info={"hostname": body.hostname[:64]})
    with SessionLocal() as db:
        db.add(node)
        db.commit()
        node_id = node.id
    return {"node_id": node_id, "secret": secret, "name": name, "domain": domain, "ports": ports}


def node_config(node: Node) -> dict:
    full, _, _, creds, _ = manager.active_state()
    s = full
    cfg = build_node_config({"domain": node.domain, "reality_private": node.reality_private,
                             "short_id": node.short_id, "ports": node.ports},
                            s["xhttp_path"], creds if node.enabled else [],
                            bool(s.get("ext", {}).get("adblock", {}).get("enabled")))
    version = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]
    return {"version": version, "xray": cfg, "domain": node.domain, "name": node.name,
            "xray_update": int(s.get("xray_update_seq", 0)), "cmd": _commands.get(node.id)}


@public.get("/config")
def get_config(node: Node = Depends(node_auth)):
    return node_config(node)


class ReportIn(BaseModel):
    traffic: dict[str, list[int]] = {}
    online: dict[str, dict[str, int]] = {}
    metrics: dict = {}
    agent: str = ""
    xray: str = ""
    cmd_result: dict | None = None  # {"id", "result"} of a command from /config


@public.post("/report")
def report(body: ReportIn, node: Node = Depends(node_auth)):
    _reports[node.id] = (time.time(), body.online)
    if body.cmd_result and body.cmd_result.get("id"):
        cid = str(body.cmd_result["id"])
        _results[cid] = body.cmd_result.get("result") or {}
        if _commands.get(node.id, {}).get("id") == cid:
            _commands.pop(node.id)
    traffic = {e: [int(v[0]), int(v[1])] for e, v in body.traffic.items() if len(v) == 2}
    if traffic:
        manager.add_traffic(traffic)
    with SessionLocal() as db:
        n = db.get(Node, node.id)
        n.last_seen = utcnow()
        n.info = {**(n.info or {}), "metrics": body.metrics, "agent": body.agent[:32], "xray": body.xray[:64],
                  "online": sum(len(v) for v in body.online.values())}
        db.commit()
    return {"rules": list(devices.desired.values())}


@public.get("/node-install.sh", response_class=PlainTextResponse)
def install_script():
    return (NODE_FILES / "install.sh").read_text()


@public.get("/node-sshcore.py", response_class=PlainTextResponse)
def node_sshcore():
    return (NODE_FILES / "sshcore.py").read_text()


@public.get("/node-agent.py", response_class=PlainTextResponse)
def agent_script():
    return (NODE_FILES / "agent.py").read_text()


# ---------------------------------------------------------------- admin API (panel)

def _node_out(n: Node) -> dict:
    seen = n.last_seen
    online = bool(seen and (utcnow() - seen).total_seconds() < ONLINE_AFTER)
    return {"id": n.id, "name": n.name, "address": n.address, "domain": n.domain, "country": n.country,
            "flag": flag(n.country), "ports": n.ports, "enabled": n.enabled, "online": online,
            "last_seen": int(seen.timestamp()) if seen else None, "info": n.info or {},
            "created_at": int(n.created_at.timestamp())}


@admin.get("/nodes")
def list_nodes(_: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        return [_node_out(n) for n in db.scalars(select(Node).order_by(Node.id))]


class NewNodeIn(BaseModel):
    name: str
    domain: str = ""


@admin.post("/nodes/join-token")
async def create_join_token(body: NewNodeIn, request: Request, _: str = Depends(auth.require_admin)):
    name = body.name.strip()[:64]
    if not name:
        raise HTTPException(400, "Укажите название сервера, например «Германия»")
    domain = body.domain.strip().lower()
    if domain and not re.fullmatch(r"([a-z0-9-]{1,63}\.)+[a-z]{2,63}", domain):
        raise HTTPException(400, "Некорректный домен")
    return await create_join_token_for(name, domain)


async def create_join_token_for(name: str, domain: str = "") -> dict:
    """One-time join token (1 h) + the install command for an exit node (panel and `app.cli node-token`)."""
    token = "nkl_join_" + secrets.token_urlsafe(24)
    with SessionLocal() as db:
        db.add(JoinToken(token_hash=_hash(token), name=name, domain=domain,
                         expires_at=utcnow() + timedelta(hours=1)))
        db.commit()
        master = settings_store.load(db)["sub_base_url"].rstrip("/")
    from .config import node_command
    cmd = node_command(master, token)
    return {"token": token, "command": cmd, "expires_in": 3600}


class NodePatch(BaseModel):
    name: str | None = None
    enabled: bool | None = None


@admin.patch("/nodes/{node_id}")
async def update_node(node_id: int, body: NodePatch, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            raise HTTPException(404, "Сервер не найден")
        if body.name is not None and body.name.strip():
            n.name = body.name.strip()[:64]
        if body.enabled is not None:
            n.enabled = body.enabled
        db.commit()
        return _node_out(n)


@admin.delete("/nodes/{node_id}")
def delete_node(node_id: int, _: str = Depends(auth.require_admin)):
    """Removes the node: its secret stops working, so it gets no users and drops out of subscriptions."""
    with SessionLocal() as db:
        n = db.get(Node, node_id)
        if not n:
            raise HTTPException(404, "Сервер не найден")
        db.delete(n)
        db.commit()
    _reports.pop(node_id, None)
    return {"ok": True}
