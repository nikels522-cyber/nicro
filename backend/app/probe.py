"""Blocking monitor from Russia: the relay box (Raspberry Pi) periodically connects with every VLESS
key of every server (master, relays, cluster nodes) using a hidden probe identity and reports which
ones work. Keys that fail while others pass are hidden from subscriptions (settings probe.hide_failed)
and trigger an alert. If everything fails it is the probe box's problem, so nothing is hidden."""
import asyncio
import logging
import time
import urllib.parse
from types import SimpleNamespace

import httpx

from . import settings_store
from .db import SessionLocal

log = logging.getLogger("vpnpanel.probe")
INTERVAL = 600
FRESH = 1800  # results older than this are ignored for hiding keys
DEFAULTS = {"enabled": True, "hide_failed": True}

_last: dict = {"ts": 0, "results": [], "via": None, "error": None}


def settings() -> dict:
    with SessionLocal() as db:
        return {**DEFAULTS, **settings_store.load(db).get("probe", {})}


def probe_identity(s: dict) -> SimpleNamespace:
    return SimpleNamespace(username="probe", uuid=s["probe_uuid"], ss_key=s["probe_ss_key"], hy_password="")


def _outbound(url: str) -> dict | None:
    p = urllib.parse.urlparse(url)
    if p.scheme != "vless":
        return None
    q = dict(urllib.parse.parse_qsl(p.query))
    user = {"id": p.username, "encryption": "none", **({"flow": q["flow"]} if q.get("flow") else {})}
    stream = {"network": q.get("type", "tcp"), "security": "reality", "realitySettings": {
        "serverName": q["sni"], "publicKey": q["pbk"], "shortId": q.get("sid", ""), "fingerprint": q.get("fp", "chrome")}}
    if stream["network"] == "xhttp":
        stream["xhttpSettings"] = {"path": q.get("path", "/"), "mode": q.get("mode", "auto")}
    return {"protocol": "vless", "settings": {"vnext": [{"address": p.hostname, "port": p.port, "users": [user]}]},
            "streamSettings": stream}


def targets() -> list[dict]:
    from .links import user_links
    with SessionLocal() as db:
        s = settings_store.load(db)
    out = []
    for link in user_links(probe_identity(s), s, hide_failed=False):
        ob = _outbound(link["url"])
        if ob:
            out.append({"id": link["key"], "name": link["name"].replace(" · probe", ""), "outbound": ob})
    return out


def status() -> dict:
    res = _last["results"]
    ok = [r for r in res if r.get("ok")]
    fresh = time.time() - _last["ts"] < FRESH
    failed = [r for r in res if not r.get("ok")] if (ok and fresh) else []
    return {"ts": int(_last["ts"]), "via": _last["via"], "error": _last["error"], "results": res,
            "failed_keys": [{"key": r["id"], "name": r["name"]} for r in failed], "settings": settings()}


def hidden_keys() -> set[str]:
    if not settings()["hide_failed"]:
        return set()
    return {k["key"] for k in status()["failed_keys"]}


async def run_once() -> dict:
    from .relays import AGENT_PORT
    with SessionLocal() as db:
        s = settings_store.load(db)
    relays = [r for r in s.get("relays", []) if r.get("host")]
    if not relays:
        _last.update(error="Нет точки входа в РФ для проверок", ts=time.time())
        return status()
    tg = targets()
    relay = relays[0]
    try:
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(f"http://{relay['host']}:{AGENT_PORT}/probe", json={"targets": tg},
                             headers={"Authorization": f"Bearer {s['relay_token']}"})
            r.raise_for_status()
            results = r.json()
    except (httpx.HTTPError, ValueError) as e:
        _last.update(error=f"{relay['name']}: {type(e).__name__}", ts=time.time())
        return status()
    names = {t["id"]: t["name"] for t in tg}
    _last.update(ts=time.time(), via=relay["name"], error=None,
                 results=[{**x, "name": names.get(x["id"], x["id"])} for x in results])
    return status()


async def loop():
    await asyncio.sleep(60)
    while True:
        try:
            if settings()["enabled"]:
                await run_once()
        except Exception:
            log.exception("probe failed")
        await asyncio.sleep(INTERVAL)
