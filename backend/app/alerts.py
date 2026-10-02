"""Alerts to owners' Telegram: something breaks -> 🔴 once, it recovers -> 🟢 once.

Checks every minute: core services, relays (entry points) and their power, cluster nodes, CPU/RAM
(sustained 5 min) and disk, TLS certificates (< 14 days), keys that stopped passing the probe
from Russia (probe.py). Thresholds live in settings["alerts"]."""
import asyncio
import logging
import socket
import ssl
import time
from collections import deque
from urllib.parse import urlparse

from sqlalchemy import select

from . import config, settings_store
from .cores import service_states
from .db import Node, SessionLocal, utcnow

log = logging.getLogger("vpnpanel.alerts")
DEFAULTS = {"enabled": True, "cpu": 90, "mem": 90, "disk": 90}
CHECK_EVERY = 60
CERT_EVERY = 6 * 3600

_state: dict[str, dict] = {}  # key -> {"text", "since"}
_cpu: deque = deque(maxlen=5)
_certs: dict[str, int] = {}  # domain -> days left
_last_cert_check = 0.0


def settings() -> dict:
    with SessionLocal() as db:
        return {**DEFAULTS, **settings_store.load(db).get("alerts", {})}


def active() -> list[dict]:
    return [{"key": k, "text": v["text"], "since": int(v["since"])} for k, v in _state.items()]


def _cert_days(host: str, port: int, sni: str) -> int | None:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=sni) as tls:
                exp = ssl.cert_time_to_seconds(tls.getpeercert()["notAfter"])
        return int((exp - time.time()) // 86400)
    except (OSError, ssl.SSLError, KeyError, ValueError):
        return None


def _check_certs(s: dict):
    global _last_cert_check
    if time.time() - _last_cert_check < CERT_EVERY:
        return
    _last_cert_check = time.time()
    port = int(config.STEAL_TARGET.rsplit(":", 1)[1])
    for name in settings_store.steal_names(s):
        _certs[name] = _cert_days("127.0.0.1", port, name)
    panel = urlparse(s["sub_base_url"])
    if panel.hostname:
        _certs[panel.hostname] = _cert_days(panel.hostname, panel.port or 443, panel.hostname)


async def _conditions() -> dict[str, str]:
    """key -> problem text for everything that is wrong right now."""
    from .monitor import monitor
    from .probe import status as probe_status
    from .relays import relay_monitor
    cfg = settings()
    with SessionLocal() as db:
        s = settings_store.load(db)
        nodes = list(db.scalars(select(Node).where(Node.enabled)))
    bad: dict[str, str] = {}

    services = ["xray", "caddy"] + (["hysteria-server"] if s["protocols"].get("hy") else [])
    for name, st in (await service_states(services)).items():
        if st != "active":
            bad[f"svc:{name}"] = f"Сервис {name} на главном сервере не работает ({st})"

    for r in relay_monitor.summary():
        if not r.get("online"):
            bad[f"relay:{r['host']}"] = f"Точка входа {r['name']} ({r['host']}) недоступна — ключи через неё не работают"
        thr = (r.get("metrics") or {}).get("throttled")
        if thr and int(thr, 16) & 0x1:
            bad[f"power:{r['host']}"] = f"У {r['name']} недостаточное питание — нужен блок питания 5V 3A"

    now = utcnow()
    for n in nodes:
        if not n.last_seen or (now - n.last_seen).total_seconds() > 90:
            bad[f"node:{n.id}"] = f"Сервер кластера «{n.name}» ({n.address}) не выходит на связь"

    m = monitor.latest
    if m:
        _cpu.append(m["cpu"])
        if len(_cpu) == _cpu.maxlen and min(_cpu) >= cfg["cpu"]:
            bad["cpu"] = f"Процессор главного сервера загружен > {cfg['cpu']}% уже 5 минут"
        if m["mem_used"] / m["mem_total"] * 100 >= cfg["mem"]:
            bad["mem"] = f"Память главного сервера заполнена на {m['mem_used'] / m['mem_total']:.0%}"
        if m["disk_used"] / m["disk_total"] * 100 >= cfg["disk"]:
            bad["disk"] = f"Диск главного сервера заполнен на {m['disk_used'] / m['disk_total']:.0%}"
        for n in nodes:
            nm = (n.info or {}).get("metrics") or {}
            if nm.get("disk_total") and nm["disk_used"] / nm["disk_total"] * 100 >= cfg["disk"]:
                bad[f"ndisk:{n.id}"] = f"Диск сервера «{n.name}» заполнен на {nm['disk_used'] / nm['disk_total']:.0%}"

    await asyncio.to_thread(_check_certs, s)
    for domain, days in _certs.items():
        if days is not None and days < 14:
            bad[f"cert:{domain}"] = f"Сертификат {domain} истекает через {days} дн. (автопродление не сработало)"

    for key in probe_status().get("failed_keys", []):
        bad[f"probe:{key['key']}"] = f"Ключ «{key['name']}» не проходит проверку из РФ — скрыт из подписок"
    return bad


async def check_once():
    from .telegram import bot
    cfg = settings()
    bad = await _conditions()
    new = {k: v for k, v in bad.items() if k not in _state}
    fixed = {k: v for k, v in _state.items() if k not in bad}
    for k, text in new.items():
        _state[k] = {"text": text, "since": time.time()}
    for k in fixed:
        _state.pop(k)
    if not cfg["enabled"] or not bot.token():
        return
    for text in new.values():
        await bot.send_admins(f"🔴 <b>nicro:</b> {text}")
    for v in fixed.values():
        await bot.send_admins(f"🟢 <b>nicro:</b> исправлено — {v['text']}")


async def loop():
    await asyncio.sleep(90)  # let relays/nodes report after a restart before alerting
    while True:
        try:
            await check_once()
        except Exception:
            log.exception("alert check failed")
        await asyncio.sleep(CHECK_EVERY)
