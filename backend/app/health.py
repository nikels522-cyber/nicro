"""Server availability: minute samples per server (HealthDaily), failover for subscriptions, the public
status page (/status) and the weekly report to the owners."""
import asyncio
import html
import logging
import time
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert

from . import settings_store
from .db import HealthDaily, Payment, SessionLocal, SupportMessage, TrafficDaily, User, today, utcnow

log = logging.getLogger("vpnpanel.health")
RELAY_DOWN_AFTER = 180  # seconds without an answer from the relay agent -> its keys leave subscriptions
NODE_DOWN_AFTER = 120
GB = 1024 ** 3


def servers() -> list[dict]:
    """[{id, name, kind, up}] for the main server, relays and nodes."""
    from .cluster import enabled_nodes, flag
    from .relays import relay_monitor
    with SessionLocal() as db:
        s = settings_store.load(db)
    out = [{"id": "main", "name": settings_store.main_label(s), "kind": "main", "up": True}]
    now = time.time()
    for i, r in enumerate(s.get("relays", [])):
        if not r.get("host"):
            continue
        st = relay_monitor.state.get(r["host"])
        up = bool(st and st.get("online"))
        out.append({"id": f"r{i}", "name": f"🇷🇺 {r['name']}", "kind": "relay", "up": up, "host": r["host"],
                    "down_for": 0 if up or not st else now - (st.get("last_seen") or _started)})
    for n in enabled_nodes():
        age = (utcnow() - n.last_seen).total_seconds() if n.last_seen else 1e9
        out.append({"id": f"n{n.id}", "name": f"{flag(n.country)} {n.name}", "kind": "node", "up": age < 30,
                    "node_id": n.id, "down_for": 0 if age < 30 else age})
    return out


_started = time.time()


def dead_entries() -> tuple[set[str], set[int]]:
    """(relay hosts, node ids) that are down long enough to be left out of subscriptions."""
    with SessionLocal() as db:
        if not settings_store.ext(settings_store.load(db), "failover")["enabled"]:
            return set(), set()
    relays, nodes = set(), set()
    for sv in servers():
        if sv["kind"] == "relay" and not sv["up"] and sv["down_for"] > RELAY_DOWN_AFTER:
            relays.add(sv["host"])
        if sv["kind"] == "node" and not sv["up"] and sv["down_for"] > NODE_DOWN_AFTER:
            nodes.add(sv["node_id"])
    return relays, nodes


async def loop():
    await asyncio.sleep(90)  # let the monitors gather a first state
    while True:
        try:
            day = today()
            with SessionLocal() as db:
                for sv in servers():
                    stmt = insert(HealthDaily).values(server=sv["id"], day=day, ok=int(sv["up"]), total=1)
                    db.execute(stmt.on_conflict_do_update(
                        index_elements=["server", "day"],
                        set_={"ok": HealthDaily.ok + int(sv["up"]), "total": HealthDaily.total + 1}))
                db.commit()
            await weekly_report_if_due()
        except Exception:
            log.exception("health sample failed")
        await asyncio.sleep(60)


def uptime(server: str, days: int) -> float | None:
    since = today() - timedelta(days=days - 1)
    with SessionLocal() as db:
        ok, total = db.execute(select(func.sum(HealthDaily.ok), func.sum(HealthDaily.total))
                               .where(HealthDaily.server == server, HealthDaily.day >= since)).one()
    return round(ok / total * 100, 2) if total else None


def daily(server: str, days: int = 30) -> list[float | None]:
    since = today() - timedelta(days=days - 1)
    with SessionLocal() as db:
        rows = {r.day: r for r in db.scalars(select(HealthDaily).where(HealthDaily.server == server,
                                                                       HealthDaily.day >= since))}
    return [round(rows[d].ok / rows[d].total * 100, 1) if d in rows and rows[d].total else None
            for d in (since + timedelta(days=i) for i in range(days))]


# ------------------------------------------------------------------ public status page

def render_status(L: str = "ru") -> str:
    from .i18n import FLAGS, LANGS, t
    with SessionLocal() as db:
        cfg = settings_store.ext(settings_store.load(db), "status")
    e = html.escape
    items = []
    for sv in servers():
        bars = "".join(
            f'<i class="{"n" if v is None else "g" if v >= 99.5 else "y" if v >= 95 else "r"}" '
            f'title="{t(L, "нет данных") if v is None else f"{v}%"}"></i>' for v in daily(sv["id"]))
        up30 = uptime(sv["id"], 30)
        items.append(f'<div class="card"><div class="row"><b>{e(t(L, sv["name"]))}</b>'
                     f'<span class="pill {"ok" if sv["up"] else "bad"}">{t(L, "работает") if sv["up"] else t(L, "недоступен")}</span></div>'
                     f'<div class="bars">{bars}</div><div class="muted">{t(L, "30 дней · доступность")} '
                     f'{"—" if up30 is None else f"{up30:g}%"}</div></div>')
    all_up = all(sv["up"] for sv in servers())
    return f"""<!doctype html><html lang="{L}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60"><meta name="robots" content="noindex"><title>{e(t(L, cfg['title']))}</title><style>
:root{{color-scheme:dark}}body{{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:#0a0b14;color:#eceef6;padding:24px 16px;
background-image:radial-gradient(40rem 24rem at 50% -8rem,rgba(124,108,255,.25),transparent)}}main{{max-width:620px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 4px}}.muted{{color:#8b8fa8;font-size:13px}}.card{{background:#12131f;border:1px solid #23253a;border-radius:18px;padding:16px;margin:12px 0}}
.row{{display:flex;justify-content:space-between;align-items:center;gap:8px}}.pill{{padding:3px 10px;border-radius:99px;font-size:13px;font-weight:700;white-space:nowrap}}
.ok{{background:rgba(52,211,153,.15);color:#6ee7b7}}.bad{{background:rgba(248,113,113,.15);color:#fca5a5}}
.bars{{display:flex;gap:3px;margin:12px 0 6px}}.bars i{{flex:1;height:28px;border-radius:4px}}.g{{background:#34d399}}.y{{background:#fbbf24}}.r{{background:#f87171}}.n{{background:#23253a}}
.head{{display:flex;align-items:center;gap:10px;margin-bottom:14px}}.langs{{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin-top:16px}}.langs a{{color:#8b8fa8;text-decoration:none;font-size:13px;padding:4px 9px;border-radius:99px;border:1px solid #23253a}}.langs a.on{{color:#eceef6;border-color:#7c6cff}}.logo{{width:38px;height:38px;border-radius:12px;background:linear-gradient(135deg,#7c6cff,#22d3ee);display:grid;place-items:center;font-weight:800;color:#0a0b14}}
</style></head><body><main><div class="head"><div class="logo">n</div><div><h1>{e(t(L, cfg['title']))}</h1>
<div class="muted">{t(L, "Все серверы работают") if all_up else t(L, "Есть недоступные серверы — подключайтесь через другой сервер в приложении")}</div></div></div>
{''.join(items)}<p class="muted">{t(L, "Страница обновляется каждую минуту.")}</p>
<div class="langs">{"".join(f'<a href="?lang={k}" class="{"on" if k == L else ""}">{FLAGS[k]} {v}</a>' for k, v in LANGS.items())}</div></main></body></html>"""


# ------------------------------------------------------------------ weekly report

async def weekly_report_if_due(force: bool = False) -> bool:
    from datetime import datetime
    with SessionLocal() as db:
        s = settings_store.load(db)
    cfg = settings_store.ext(s, "report")
    now = datetime.now()  # server local time
    week = now.strftime("%G-W%V")
    if not force and (not cfg["enabled"] or now.weekday() != int(cfg["weekday"]) or now.hour < int(cfg["hour"])
                      or cfg.get("last") == week):
        return False
    from .telegram import bot
    sent = await bot.send_admins(weekly_text())
    if not force:
        with SessionLocal() as db:
            s = settings_store.load(db)
            s.setdefault("ext", {}).setdefault("report", {})["last"] = week
            settings_store.save(db, s)
    return bool(sent)


def weekly_text() -> str:
    since = utcnow() - timedelta(days=7)
    day0 = today() - timedelta(days=6)
    with SessionLocal() as db:
        users = list(db.scalars(select(User)))
        new = [u for u in users if u.created_at >= since]
        pays = list(db.scalars(select(Payment).where(Payment.status == "paid", Payment.paid_at >= since, Payment.amount > 0)))
        traffic = db.execute(select(TrafficDaily.user_id, func.sum(TrafficDaily.up + TrafficDaily.down))
                             .where(TrafficDaily.day >= day0).group_by(TrafficDaily.user_id)).all()
        unread = db.scalar(select(func.count()).select_from(SupportMessage)
                           .where(SupportMessage.direction == "in", ~SupportMessage.read)) or 0
    names = {u.id: u.username for u in users}
    total = sum(t for _, t in traffic)
    top = sorted(traffic, key=lambda r: -r[1])[:5]
    now = utcnow()
    expiring = [u for u in users if u.expire_at and now < u.expire_at <= now + timedelta(days=7)]
    st = [u.status(now) for u in users]
    lines = ["📈 <b>nicro · отчёт за неделю</b>",
             f"👥 Клиентов: {len(users)} (новых {len(new)}) · активных {st.count('active')}",
             f"💰 Оплат: {len(pays)} на {sum(p.amount for p in pays):.0f} ₽",
             f"📊 Трафик: {total / GB:.1f} ГБ"]
    if top:
        lines.append("🏆 " + ", ".join(f"{html.escape(names.get(uid, '?'))} {t / GB:.1f} ГБ" for uid, t in top))
    lines.append(f"⏳ Истекают в ближайшие 7 дней: {len(expiring)}" +
                 (" — " + ", ".join(html.escape(u.username) for u in expiring[:10]) if expiring else ""))
    for sv in servers():
        up = uptime(sv["id"], 7)
        lines.append(f"{'🟢' if sv['up'] else '🔴'} {html.escape(sv['name'])}: {'—' if up is None else f'{up:g}%'} за 7 дней")
    if unread:
        lines.append(f"💬 Неотвеченных обращений: {unread}")
    return "\n".join(lines)
