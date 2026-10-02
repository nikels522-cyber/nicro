import asyncio
import base64
import csv
import io
import re
import secrets
import time
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Response, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import auth, config, settings_store
from .config import MANAGED_SERVICES
from .cores import service_states, systemctl
from .cores.devices import devices
from .cores.hysteria import hysteria
from .cores.manager import manager
from .db import Admin, AuditLog, Device, Payment, Plan, ServerDaily, SessionLocal, TrafficDaily, User, device_email, today, utcnow
from .links import sub_url, telegram_proxy, user_links
from .monitor import monitor
from .relays import relay_monitor
from .telegram import bot, invite_link, status_text
from . import alerts, audit, backup, billing, probe, totp, updates
from . import smartlink, sshctl
from .firewall import PanelFirewall, firewall, parse_net

router = APIRouter()
GB = 1024 ** 3


def get_db():
    with SessionLocal() as db:
        yield db


def ts(dt: datetime | None) -> int | None:
    return int(dt.replace(tzinfo=timezone.utc).timestamp()) if dt else None


def from_ts(v: int | None) -> datetime | None:
    return datetime.fromtimestamp(v, timezone.utc).replace(tzinfo=None) if v else None


def user_out(u: User, now: datetime | None = None) -> dict:
    last = manager.online.get(u.username)
    return {
        "id": u.id, "username": u.username, "status": u.status(now), "enabled": u.enabled,
        "data_limit": u.data_limit, "used_up": u.used_up, "used_down": u.used_down, "used": u.used,
        "expire_at": ts(u.expire_at), "created_at": ts(u.created_at), "last_online": ts(u.last_online),
        "online": bool(last and time.time() - last < 60), "note": u.note, "multi_device": u.multi_device,
        "devices_online": devices.online_count(u.username),  # see cores/devices.py
        "tg_id": u.tg_id, "plan_id": u.plan_id, "reset_monthly": u.reset_monthly, "l2tp_enabled": u.l2tp_enabled,
        "parent_id": u.parent_id, "speed_mbps": u.speed_mbps, "referred_by": u.referred_by,
        "pending_signup": bool((u.notified or {}).get("pending_signup")),
        "hide_ip": u.hide_ip,
    }


# ---------- auth ----------

class LoginIn(BaseModel):
    username: str
    password: str
    code: str = ""  # 2FA code when enabled


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = auth.client_ip(request)
    auth.check_rate_limit(ip)
    admin = db.scalar(select(Admin).where(Admin.username == body.username))
    if not admin or not auth.verify_password(body.password, admin.password_hash):
        auth.register_failure(ip)
        raise HTTPException(401, "Неверный логин или пароль")
    if admin.totp_enabled:
        if not body.code:
            raise HTTPException(401, "2FA_REQUIRED")
        if not totp.verify(admin.totp_secret, body.code):
            auth.register_failure(ip)
            raise HTTPException(401, "Неверный код 2FA")
    return {"token": auth.make_token(admin.username), "username": admin.username, "role": admin.role}


@router.get("/auth/me")
def me(name: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    a = db.scalar(select(Admin).where(Admin.username == name))
    return {"username": a.username, "role": a.role, "totp_enabled": a.totp_enabled, "tg_id": a.tg_id}


class TotpIn(BaseModel):
    secret: str = ""
    code: str


@router.get("/auth/2fa/setup")
def totp_setup(name: str = Depends(auth.require_admin)):
    secret = totp.new_secret()
    return {"secret": secret, "uri": totp.uri(secret, name)}


@router.post("/auth/2fa/enable")
def totp_enable(body: TotpIn, name: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    if not totp.verify(body.secret, body.code):
        raise HTTPException(400, "Код не подошёл — проверьте время на телефоне и введите свежий код")
    a = db.scalar(select(Admin).where(Admin.username == name))
    a.totp_secret, a.totp_enabled = body.secret, True
    db.commit()
    return {"ok": True}


@router.post("/auth/2fa/disable")
def totp_disable(body: TotpIn, name: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    a = db.scalar(select(Admin).where(Admin.username == name))
    if a.totp_enabled and not totp.verify(a.totp_secret, body.code):
        raise HTTPException(400, "Неверный код 2FA")
    a.totp_secret, a.totp_enabled = "", False
    db.commit()
    return {"ok": True}


class PasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


@router.post("/auth/password")
def change_password(body: PasswordIn, name: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    admin = db.scalar(select(Admin).where(Admin.username == name))
    if not admin or not auth.verify_password(body.old_password, admin.password_hash):
        raise HTTPException(400, "Текущий пароль неверен")
    admin.password_hash = auth.hash_password(body.new_password)
    db.commit()
    return {"ok": True}


# ---------- system ----------

async def system_payload() -> dict:
    with SessionLocal() as db:
        now = utcnow()
        users = list(db.scalars(select(User)))
        counts = {"total": len(users), "active": 0, "disabled": 0, "expired": 0, "limited": 0}
        for u in users:
            counts[u.status(now)] += 1
        total_traffic = sum(u.used for u in users)
        s = settings_store.load(db)
    online_cut = time.time() - 60
    counts["online"] = sum(1 for t in manager.online.values() if t > online_cut)
    # services switched off on purpose (protocol disabled) are not an outage — don't show them red
    services = [x for x in MANAGED_SERVICES if not (x == "hysteria-server" and not s["protocols"].get("hy"))]
    return {"metrics": monitor.latest, "users": counts, "traffic_total": total_traffic,
            "services": await service_states(services), "hy_online": await hysteria.online(s),
            "relays": relay_monitor.summary()}


@router.get("/system")
async def system(_: str = Depends(auth.require_admin)):
    return await system_payload()


@router.get("/relays/status")
def relays_status(_: str = Depends(auth.require_admin)):
    return relay_monitor.with_history()


@router.get("/telegram")
def telegram(_: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    return telegram_proxy(settings_store.load(db))


@router.get("/system/history")
def system_history(_: str = Depends(auth.require_admin)):
    return list(monitor.history)


@router.post("/services/{name}/restart")
async def restart_service(name: str, _: str = Depends(auth.require_admin)):
    if name not in MANAGED_SERVICES:
        raise HTTPException(404, "Неизвестный сервис")
    if name == "xray" or name == "hysteria-server":
        await manager.sync(force_restart=True)
    else:
        await systemctl("restart", name)
    return {"ok": True}


@router.websocket("/ws")
async def ws(websocket: WebSocket):
    if not auth.decode_token(websocket.query_params.get("token", "")):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        tick = 0
        payload = await system_payload()
        while True:
            if tick % 5 == 0:  # full payload (services, counts) every 10s
                payload = await system_payload()
            else:
                payload["metrics"] = monitor.latest
            await websocket.send_json(payload)
            tick += 1
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError):
        pass


@router.get("/stats/traffic")
def traffic_stats(days: int = 30, _: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    since = today() - timedelta(days=days - 1)
    users = db.execute(select(TrafficDaily.day, func.sum(TrafficDaily.up), func.sum(TrafficDaily.down))
                       .where(TrafficDaily.day >= since).group_by(TrafficDaily.day)).all()
    server = db.execute(select(ServerDaily).where(ServerDaily.day >= since)).scalars().all()
    by_day = {since + timedelta(days=i): {"day": str(since + timedelta(days=i)), "up": 0, "down": 0,
                                          "server_rx": 0, "server_tx": 0} for i in range(days)}
    for d, up, down in users:
        by_day[d].update(up=int(up or 0), down=int(down or 0))
    for row in server:
        if row.day in by_day:
            by_day[row.day].update(server_rx=row.rx, server_tx=row.tx)
    top = db.execute(select(User.username, (func.sum(TrafficDaily.up) + func.sum(TrafficDaily.down)).label("t"))
                     .join(TrafficDaily, TrafficDaily.user_id == User.id).where(TrafficDaily.day >= since)
                     .group_by(User.username).order_by(func.sum(TrafficDaily.up + TrafficDaily.down).desc())
                     .limit(8)).all()
    return {"daily": list(by_day.values()), "top": [{"username": n, "total": int(t or 0)} for n, t in top]}


# ---------- users ----------

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{2,32}$")
HOST_RE = re.compile(r"^[A-Za-z0-9.\-:]{3,253}$")
DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}$")


class UserIn(BaseModel):
    username: str
    data_limit_gb: float = 0
    expire_at: int | None = None  # unix seconds
    note: str = ""
    multi_device: bool = True
    tg_id: str = ""
    plan_id: int | None = None  # create with a plan: period, limit, devices from it
    amount: float | None = None  # money received (defaults to the plan price)


class UserPatch(BaseModel):
    enabled: bool | None = None
    multi_device: bool | None = None
    tg_id: str | None = None
    data_limit_gb: float | None = None
    expire_at: int | None = None
    clear_expire: bool = False
    note: str | None = None
    reset_monthly: bool | None = None
    l2tp_enabled: bool | None = None
    speed_mbps: int | None = None
    hide_ip: bool | None = None


TG_ID_RE = re.compile(r"^-?\d{4,20}$")


def _check_tg_id(v: str) -> str:
    v = v.strip()
    if v and not TG_ID_RE.match(v):
        raise HTTPException(400, "Telegram ID — это число, его присылает бот по команде /start")
    return v


def _get_user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    return u


def _new_secrets() -> dict:
    return {"uuid": str(uuidlib.uuid4()), "ss_key": settings_store.gen_ss_key(),
            "hy_password": secrets.token_urlsafe(18), "sub_token": secrets.token_urlsafe(24)}


@router.get("/users")
def list_users(_: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    now = utcnow()
    s = settings_store.load(db)
    return [{**user_out(u, now), "smart_link": smartlink.url(u, s)} for u in db.scalars(select(User).order_by(User.id.desc()))]


@router.post("/users")
async def create_user(body: UserIn, admin: str = Depends(auth.require_admin)):
    if not USERNAME_RE.match(body.username):
        raise HTTPException(400, "Имя: 2–32 символа, латиница, цифры, _ . -")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == body.username)):
            raise HTTPException(409, "Пользователь уже существует")
        u = User(username=body.username, data_limit=int(body.data_limit_gb * GB),
                 expire_at=from_ts(body.expire_at), note=body.note, multi_device=body.multi_device,
                 tg_id=_check_tg_id(body.tg_id), **_new_secrets())
        u.hide_ip = bool(settings_store.load(db).get("hide_ip_new", True))
        db.add(u)
        db.flush()
        if body.plan_id:
            plan = db.get(Plan, body.plan_id)
            if not plan:
                raise HTTPException(404, "Тариф не найден")
            billing.apply_plan(u, plan)
            billing.record(db, u, plan, body.amount if body.amount is not None else plan.price,
                           f"новый клиент, тариф «{plan.name}»", admin)
        db.commit()
        out = user_out(u)
    await manager.sync()
    return out


@router.get("/users/{user_id}")
def get_user(user_id: int, _: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    u = _get_user(db, user_id)
    s = settings_store.load(db)
    since = today() - timedelta(days=29)
    rows = {r.day: r for r in db.scalars(select(TrafficDaily).where(TrafficDaily.user_id == u.id,
                                                                     TrafficDaily.day >= since))}
    daily = []
    for i in range(30):
        d = since + timedelta(days=i)
        r = rows.get(d)
        daily.append({"day": str(d), "up": r.up if r else 0, "down": r.down if r else 0})
    from . import growth
    parent = db.get(User, u.parent_id) if u.parent_id else None
    members = list(db.scalars(select(User).where(User.parent_id == u.id).order_by(User.id)))
    plan = db.get(Plan, u.plan_id) if u.plan_id else None
    promo = growth.pending_discount(u)
    return {**user_out(u), "links": user_links(u, s), "sub_url": sub_url(u, s), "daily": daily,
            "devices": devices_out(db, u), "invite_link": invite_link(u), "smart_link": smartlink.url(u, s),
            "l2tp": l2tp_out(u, s),
            "family": {"parent": {"id": parent.id, "username": parent.username} if parent else None,
                       "members": [user_out(m) for m in members],
                       "limit": plan.family_size if plan else None},
            "referral": growth.referral_stats(db, u),
            "promo": {"code": promo.code, "value": promo.value} if promo else None}


class FamilyIn(BaseModel):
    username: str


@router.post("/users/{user_id}/family")
async def add_family_member(user_id: int, body: FamilyIn, admin: str = Depends(auth.require_admin)):
    """A family member: own keys and devices, the head's period and a shared traffic limit."""
    if not USERNAME_RE.match(body.username):
        raise HTTPException(400, "Имя: 2–32 символа, латиница, цифры, _ . -")
    with SessionLocal() as db:
        head = _get_user(db, user_id)
        if head.parent_id:
            raise HTTPException(400, "Это участник семьи — добавляйте участников главному аккаунту")
        if db.scalar(select(User).where(User.username == body.username)):
            raise HTTPException(409, "Пользователь уже существует")
        plan = db.get(Plan, head.plan_id) if head.plan_id else None
        count = db.scalar(select(func.count()).select_from(User).where(User.parent_id == head.id))
        if plan and plan.family_size and count >= plan.family_size:
            raise HTTPException(400, f"По тарифу «{plan.name}» в семье до {plan.family_size + 1} человек")
        m = User(username=body.username, parent_id=head.id, multi_device=head.multi_device,
                 note=f"семья {head.username}", speed_mbps=head.speed_mbps, **_new_secrets())
        db.add(m)
        db.commit()
        out = user_out(m)
    await manager.sync()
    return out


@router.delete("/users/{user_id}/family/{member_id}")
async def detach_family_member(user_id: int, member_id: int, _: str = Depends(auth.require_admin)):
    """Detaches a member; it keeps its keys but gets no access of its own (disabled)."""
    with SessionLocal() as db:
        m = _get_user(db, member_id)
        if m.parent_id != user_id:
            raise HTTPException(404, "Не участник этой семьи")
        m.parent_id, m.enabled = None, False
        db.commit()
    await manager.sync()
    return {"ok": True}


class PromoApplyIn(BaseModel):
    code: str


@router.post("/users/{user_id}/promo")
async def apply_promo(user_id: int, body: PromoApplyIn, _: str = Depends(auth.require_admin)):
    from . import growth
    try:
        msg = growth.redeem(user_id, body.code)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await manager.sync()
    return {"message": msg}


class PayLinkIn(BaseModel):
    plan_id: int
    provider: str


@router.post("/users/{user_id}/pay-link")
async def pay_link(user_id: int, body: PayLinkIn, _: str = Depends(auth.require_admin)):
    """A payment link to send to the client (any enabled provider)."""
    from . import payments
    try:
        return await payments.create_order(user_id, body.plan_id, body.provider)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


def l2tp_out(u: User, s: dict) -> dict | None:
    from . import l2tp
    cfg = s.get("ext", {}).get("l2tp", {})
    if not cfg.get("enabled") or not u.l2tp_enabled:
        return None
    return {"server": s["host"], "psk": cfg.get("psk", ""), "login": u.username, "password": u.l2tp_password,
            "online": any(user == u.username for user, _ in l2tp.sessions().values())}


def devices_out(db: Session, u: User) -> list[dict]:
    """Registered devices (online or not) + addresses using the plain key that are online now."""
    out = []
    for d in db.scalars(select(Device).where(Device.user_id == u.id).order_by(Device.id)):
        unit = devices.device_online(device_email(d.id, u.username))
        out.append({"id": d.id, "kind": "device", "name": d.model or d.os or "Устройство",
                    "os": " ".join(x for x in (d.os, d.os_version) if x), "app": d.app,
                    "enabled": d.enabled, "online": bool(unit) and not unit["blocked"],
                    "blocked": bool(unit and unit["blocked"]), "ips": unit["ips"] if unit else [],
                    "last_seen": unit["last_seen"] if unit else ts(d.last_online),
                    "created_at": ts(d.created_at)})
    for unit in devices.units.get(u.username, []):
        if unit["kind"] == "l2tp":
            out.append({"id": None, "kind": "l2tp", "name": "L2TP/IPsec", "os": "", "app": "встроенный VPN",
                        "enabled": True, "online": not unit["blocked"], "blocked": unit["blocked"],
                        "ips": unit["ips"], "last_seen": unit["last_seen"], "created_at": None})
        if unit["kind"] == "ip":
            out.append({"id": None, "kind": "ip", "name": "По общему ключу", "os": "", "app": "",
                        "enabled": True, "online": not unit["blocked"], "blocked": unit["blocked"],
                        "ips": unit["ips"], "last_seen": unit["last_seen"], "created_at": None})
    return out


@router.post("/users/{user_id}/telegram-test")
async def telegram_test(user_id: int, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        u = _get_user(db, user_id)
        if not u.tg_id:
            raise HTTPException(400, "У клиента не указан Telegram ID")
        text = "🔔 Тестовое сообщение от nicro VPN.\nУведомления настроены.\n\n" + status_text(u)
        chat = u.tg_id
    try:
        await bot.send(chat, text)
    except Exception as e:
        raise HTTPException(400, f"Telegram: {e}. Клиент должен сначала написать боту /start")
    return {"ok": True}


# ---------- telegram bot ----------

@router.get("/telegram-bot")
def telegram_bot_info(_: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    token = settings_store.load(db).get("tg_bot_token", "")
    linked = db.scalar(select(func.count()).select_from(User).where(User.tg_id != ""))
    return {"configured": bool(token), "username": bot.username,
            "token_hint": f"{token[:6]}…{token[-4:]}" if token else "", "linked_users": linked}


class BotTokenIn(BaseModel):
    token: str


@router.put("/telegram-bot")
async def telegram_bot_set(body: BotTokenIn, _: str = Depends(auth.require_admin)):
    token = body.token.strip()
    username = None
    if token:
        try:
            username = await bot.check_token(token)
        except Exception as e:
            raise HTTPException(400, f"Токен не подходит: {e}")
    with SessionLocal() as db:
        s = settings_store.load(db)
        s["tg_bot_token"] = token
        settings_store.save(db, s)
    bot.username = username
    return {"configured": bool(token), "username": username}


# ---------- panel firewall ----------

class FwRule(BaseModel):
    cidr: str
    note: str = ""


class FirewallIn(BaseModel):
    enabled: bool
    via_vpn: bool
    allow: list[FwRule]


def _fw_out(s: dict, request: Request) -> dict:
    return {**s["panel_fw"], "your_ip": auth.client_ip(request), "server_ip": s["host"],
            "active": firewall.enabled, "denied": list(firewall.denied)}


@router.get("/firewall")
def get_firewall(request: Request, _: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    return _fw_out(settings_store.load(db), request)


@router.put("/firewall")
def put_firewall(body: FirewallIn, request: Request, _: str = Depends(auth.require_admin),
                 db: Session = Depends(get_db)):
    rules = []
    for r in body.allow:
        try:
            net = parse_net(r.cidr)
        except ValueError:
            raise HTTPException(400, f"«{r.cidr}» — не IP-адрес и не диапазон (пример: 1.2.3.4 или 10.0.0.0/8)")
        rules.append({"cidr": str(net) if net.num_addresses > 1 else str(net.network_address), "note": r.note[:60]})
    s = settings_store.load(db)
    new = {"enabled": body.enabled, "via_vpn": body.via_vpn, "allow": rules}
    if body.enabled:  # never let the admin lock themselves out
        probe = PanelFirewall()
        probe.load({**s, "panel_fw": new})
        if not probe.enabled:
            raise HTTPException(400, "Добавьте хотя бы один адрес или включите доступ через VPN")
        ip = auth.client_ip(request)
        if not probe.allowed(ip):
            raise HTTPException(400, f"Ваш текущий IP {ip} не входит в список — вы потеряете доступ. Добавьте его.")
    s["panel_fw"] = new
    settings_store.save(db, s)
    firewall.load(s)
    return _fw_out(s, request)


# ---------- DPI bypass (zapret) on entry points ----------

class ZapretIn(BaseModel):
    action: str = "status"  # status | enable | select | disable


@router.post("/relays/{index}/zapret")
async def relay_zapret(index: int, body: ZapretIn, _: str = Depends(auth.require_admin)):
    """Runs nicro-zapret on the entry point through its agent. Test targets: TLS names the main server
    answers on its REALITY ports (the third-party SNI on the Vision port, the own domain on the self-steal port)."""
    if body.action not in ("status", "enable", "select", "disable"):
        raise HTTPException(400, "Неизвестное действие")
    with SessionLocal() as db:
        s = settings_store.load(db)
    targets = [f"{s['reality_sni']}:{s['ports']['vless']}"]
    if s.get("steal_domain"):
        targets.append(f"{s['steal_domain']}:{s['ports']['steal']}")
    try:
        res = await sshctl._relay(index, {"action": body.action, "targets": targets}, path="/zapret")
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    if not res.get("ok"):
        raise HTTPException(400, res.get("error") or "ошибка")
    return res["zapret"]


# ---------- SSH (any server of the cluster, sshctl.py) ----------

async def _ssh(server: str, cmd: dict) -> dict:
    try:
        return await sshctl.call(server, cmd)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get("/ssh/servers")
def ssh_servers(_: str = Depends(auth.require_admin)):
    return sshctl.servers()


@router.get("/ssh")
async def get_ssh(server: str = "main", _: str = Depends(auth.require_admin)):
    return (await _ssh(server, {"action": "state"}))["state"]


class SshIn(BaseModel):
    enabled: bool | None = None
    password: bool | None = None


@router.put("/ssh")
async def put_ssh(body: SshIn, server: str = "main", _: str = Depends(auth.require_admin)):
    res = None
    if body.password is not None:
        res = await _ssh(server, {"action": "password", "on": body.password})
    if body.enabled is not None:
        res = await _ssh(server, {"action": "enable", "on": body.enabled})
    return (res or await _ssh(server, {"action": "state"}))["state"]


class SshKeyIn(BaseModel):
    name: str = "admin"


@router.post("/ssh/keys")
async def create_ssh_key(body: SshKeyIn, server: str = "main", _: str = Depends(auth.require_admin)):
    if not re.match(r"^[\w .@-]{0,40}$", body.name):
        raise HTTPException(400, "Название ключа: буквы, цифры, пробел, . @ -")
    return (await _ssh(server, {"action": "genkey", "name": body.name}))["key"]


@router.delete("/ssh/keys/{fingerprint:path}")
async def delete_ssh_key(fingerprint: str, server: str = "main", _: str = Depends(auth.require_admin)):
    return (await _ssh(server, {"action": "delkey", "fingerprint": fingerprint}))["state"]


class DevicePatch(BaseModel):
    enabled: bool


@router.patch("/users/{user_id}/devices/{device_id}")
async def update_device(user_id: int, device_id: int, body: DevicePatch, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        d = db.get(Device, device_id)
        if not d or d.user_id != user_id:
            raise HTTPException(404, "Устройство не найдено")
        d.enabled = body.enabled
        db.commit()
    await manager.sync()
    return {"ok": True}


@router.delete("/users/{user_id}/devices/{device_id}")
async def delete_device(user_id: int, device_id: int, _: str = Depends(auth.require_admin)):
    """Forget a device. It re-registers on its next subscription fetch (to block it: disable)."""
    with SessionLocal() as db:
        d = db.get(Device, device_id)
        if not d or d.user_id != user_id:
            raise HTTPException(404, "Устройство не найдено")
        db.delete(d)
        db.commit()
    await manager.sync()
    return {"ok": True}


@router.patch("/users/{user_id}")
async def update_user(user_id: int, body: UserPatch, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        u = _get_user(db, user_id)
        if body.enabled is not None:
            u.enabled = body.enabled
        if body.multi_device is not None:
            u.multi_device = body.multi_device
        if body.tg_id is not None:
            u.tg_id = _check_tg_id(body.tg_id)
        if body.reset_monthly is not None:
            u.reset_monthly = body.reset_monthly
        if body.l2tp_enabled is not None:
            u.l2tp_enabled = body.l2tp_enabled
            if body.l2tp_enabled and not u.l2tp_password:
                u.l2tp_password = secrets.token_urlsafe(9)
        if body.data_limit_gb is not None:
            u.data_limit = int(body.data_limit_gb * GB)
        if body.clear_expire:
            u.expire_at = None
        elif body.expire_at is not None:
            u.expire_at = from_ts(body.expire_at)
        if body.note is not None:
            u.note = body.note
        if body.speed_mbps is not None:
            u.speed_mbps = max(0, min(body.speed_mbps, 10000))
        if body.hide_ip is not None:
            u.hide_ip = body.hide_ip
        db.commit()
        out = user_out(u)
    await manager.sync()
    return out


@router.post("/users/{user_id}/reset-traffic")
async def reset_traffic(user_id: int, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        u = _get_user(db, user_id)
        u.used_up = u.used_down = 0
        db.commit()
    await manager.sync()
    return {"ok": True}


@router.post("/users/{user_id}/regenerate")
async def regenerate(user_id: int, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        u = _get_user(db, user_id)
        for k, v in _new_secrets().items():
            setattr(u, k, v)
        for d in db.scalars(select(Device).where(Device.user_id == u.id)):  # revoke device identities too
            db.delete(d)
        db.commit()
    await manager.sync()
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        for m in db.scalars(select(User).where(User.parent_id == user_id)):
            m.parent_id, m.enabled = None, False
        db.delete(_get_user(db, user_id))
        db.commit()
    await manager.sync()
    return {"ok": True}


# ---------- settings ----------

@router.get("/settings")
def get_settings(_: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    return settings_out(settings_store.load(db))


def settings_out(s: dict) -> dict:
    out = {k: s[k] for k in settings_store.PUBLIC_FIELDS}
    out["relay_command"] = config.relay_command(s["sub_base_url"].rstrip("/"), s["relay_token"])
    out["regru"] = {"username": s["regru"].get("username", ""), "password": "***" if s["regru"].get("password") else ""}
    return out


@router.patch("/settings")
async def patch_settings(body: dict, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        s = settings_store.load(db)
        old_relays = s.get("relays", [])
        if isinstance(body.get("regru"), dict) and body["regru"].get("password") == "***":
            body["regru"]["password"] = s["regru"].get("password", "")  # masked in GET: keep
        for k, v in body.items():
            if k not in settings_store.EDITABLE_FIELDS:
                raise HTTPException(400, f"Поле {k} нельзя изменить")
            if isinstance(s[k], dict):
                s[k] = {**s[k], **v}
            else:
                s[k] = v
        if not re.match(r"^[A-Za-z0-9.\-]+$", s["reality_sni"]):
            raise HTTPException(400, "Некорректный SNI")
        if not isinstance(s["relays"], list) or not all(
                isinstance(r, dict) and HOST_RE.match(str(r.get("host", ""))) and str(r.get("name", "")).strip()
                for r in s["relays"]):
            raise HTTPException(400, "Точка входа: нужны название и адрес (IP или домен)")
        domains = [s["steal_domain"]] + [r.get("domain", "") for r in s["relays"]]
        if not all(d == "" or DOMAIN_RE.match(d) for d in domains):
            raise HTTPException(400, "Некорректный домен")
        known = {r.get("host"): r.get("machine_id") for r in old_relays}
        s["relays"] = [{"name": r["name"].strip()[:32], "host": r["host"], "domain": r.get("domain", "").strip(),
                        **({"machine_id": known[r["host"]]} if known.get(r["host"]) else {})}
                       for r in s["relays"]]
        if s["panel_domain"] and not DOMAIN_RE.match(s["panel_domain"]):
            raise HTTPException(400, "Некорректный домен панели")
        settings_store.save(db, s)
    await manager.sync()
    return settings_out(s)


@router.post("/settings/rotate-reality")
async def rotate_reality(_: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        s = settings_store.load(db)
        s["reality_private"], s["reality_public"] = settings_store.gen_reality_keys()
        s["short_id"] = secrets.token_hex(8)
        settings_store.save(db, s)
    await manager.sync()
    return {"ok": True}


# ---------- admins (owner) ----------

class AdminIn(BaseModel):
    username: str
    password: str = ""
    role: str = "operator"
    tg_id: str = ""


def _admin_out(a: Admin) -> dict:
    return {"id": a.id, "username": a.username, "role": a.role, "totp_enabled": a.totp_enabled, "tg_id": a.tg_id}


@router.get("/admins")
def list_admins(_: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    return [_admin_out(a) for a in db.scalars(select(Admin).order_by(Admin.id))]


@router.post("/admins")
def create_admin(body: AdminIn, _: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    if not USERNAME_RE.match(body.username):
        raise HTTPException(400, "Логин: 2–32 символа, латиница, цифры, _ . -")
    if body.role not in auth.ROLE_NAMES:
        raise HTTPException(400, "Неизвестная роль")
    if len(body.password) < 8:
        raise HTTPException(400, "Пароль — от 8 символов")
    if db.scalar(select(Admin).where(Admin.username == body.username)):
        raise HTTPException(409, "Такой администратор уже есть")
    a = Admin(username=body.username, password_hash=auth.hash_password(body.password), role=body.role,
              tg_id=_check_tg_id(body.tg_id))
    db.add(a)
    db.commit()
    return _admin_out(a)


@router.patch("/admins/{admin_id}")
def update_admin(admin_id: int, body: AdminIn, name: str = Depends(auth.require_admin),
                 db: Session = Depends(get_db)):
    a = db.get(Admin, admin_id)
    if not a:
        raise HTTPException(404, "Администратор не найден")
    if body.role not in auth.ROLE_NAMES:
        raise HTTPException(400, "Неизвестная роль")
    owners = db.scalar(select(func.count()).select_from(Admin).where(Admin.role == "owner"))
    if a.role == "owner" and body.role != "owner" and owners <= 1:
        raise HTTPException(400, "Нельзя убрать последнего владельца")
    a.role, a.tg_id = body.role, _check_tg_id(body.tg_id)
    if body.password:
        if len(body.password) < 8:
            raise HTTPException(400, "Пароль — от 8 символов")
        a.password_hash = auth.hash_password(body.password)
    db.commit()
    return _admin_out(a)


@router.delete("/admins/{admin_id}")
def delete_admin(admin_id: int, name: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    a = db.get(Admin, admin_id)
    if not a:
        raise HTTPException(404, "Администратор не найден")
    if a.username == name:
        raise HTTPException(400, "Нельзя удалить самого себя")
    if a.role == "owner" and db.scalar(select(func.count()).select_from(Admin).where(Admin.role == "owner")) <= 1:
        raise HTTPException(400, "Нельзя удалить последнего владельца")
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.get("/audit")
def audit_log(offset: int = 0, _: str = Depends(auth.require_admin)):
    return audit.recent(200, offset)


# ---------- bulk / CSV ----------

class BulkIn(BaseModel):
    ids: list[int]
    action: str  # extend | plan | enable | disable | reset | delete
    days: int = 0
    plan_id: int | None = None


@router.post("/users/bulk")
async def bulk(body: BulkIn, admin: str = Depends(auth.require_admin)):
    if body.action not in ("extend", "plan", "enable", "disable", "reset", "delete"):
        raise HTTPException(400, "Неизвестное действие")
    with SessionLocal() as db:
        plan = db.get(Plan, body.plan_id) if body.plan_id else None
        if body.action == "plan" and not plan:
            raise HTTPException(400, "Выберите тариф")
        users = list(db.scalars(select(User).where(User.id.in_(body.ids))))
        for u in users:
            if body.action == "extend" and body.days:
                billing.extend(u, body.days)
                billing.record(db, u, None, 0, f"массово +{body.days} дн.", admin)
            elif body.action == "plan":
                billing.apply_plan(u, plan)
                billing.record(db, u, plan, plan.price, f"массово, тариф «{plan.name}»", admin)
            elif body.action in ("enable", "disable"):
                u.enabled = body.action == "enable"
            elif body.action == "reset":
                u.used_up = u.used_down = 0
                u.notified = {}
            elif body.action == "delete":
                db.delete(u)
        db.commit()
    await manager.sync()
    return {"ok": True, "count": len(users)}


CSV_FIELDS = ["username", "status", "used_gb", "limit_gb", "expire", "multi_device", "tg_id", "note", "sub_url"]


@router.get("/export/users.csv")
def export_csv(_: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    s = settings_store.load(db)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(CSV_FIELDS)
    now = utcnow()
    for u in db.scalars(select(User).order_by(User.username)):
        w.writerow([u.username, u.status(now), round(u.used / GB, 2), round(u.data_limit / GB, 2),
                    u.expire_at.strftime("%Y-%m-%d") if u.expire_at else "", int(u.multi_device), u.tg_id,
                    u.note, sub_url(u, s)])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="nicro-users.csv"'})


class ImportIn(BaseModel):
    csv: str
    plan_id: int | None = None


@router.post("/users/import")
async def import_csv(body: ImportIn, admin: str = Depends(auth.require_admin)):
    """CSV with a header: username;days;limit_gb;note;tg_id;multi_device (only username required)."""
    text = body.csv.lstrip("﻿")
    delim = ";" if text.count(";") >= text.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
    created, skipped = [], []
    with SessionLocal() as db:
        plan = db.get(Plan, body.plan_id) if body.plan_id else None
        existing = {name for (name,) in db.execute(select(User.username))}
        for r in rows:
            name = (r.get("username") or "").strip()
            if not USERNAME_RE.match(name) or name in existing:
                skipped.append(name or "?")
                continue
            try:
                days = int(float(r.get("days") or 0))
                limit = float(r.get("limit_gb") or 0)
                tg = _check_tg_id(r.get("tg_id") or "")
            except (ValueError, HTTPException):
                skipped.append(name)
                continue
            u = User(username=name, note=(r.get("note") or "")[:500], tg_id=tg,
                     multi_device=(r.get("multi_device") or "1").strip() not in ("0", "false", "нет"),
                     data_limit=int(limit * GB), expire_at=utcnow() + timedelta(days=days) if days else None,
                     **_new_secrets())
            db.add(u)
            db.flush()
            if plan:
                billing.apply_plan(u, plan)
                billing.record(db, u, plan, plan.price, "импорт", admin)
            existing.add(name)
            created.append(name)
        db.commit()
    await manager.sync()
    return {"created": created, "skipped": skipped}



@router.post("/users/{user_id}/send-sub")
async def send_sub(user_id: int, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        u = _get_user(db, user_id)
    if not u.tg_id:
        raise HTTPException(400, "Клиент ещё не привязан к Telegram — отправьте ему ссылку-приглашение")
    try:
        await bot.send_subscription(u)
    except Exception as e:
        raise HTTPException(400, f"Telegram: {e}")
    return {"ok": True}


# ---------- backups (owner) ----------

@router.get("/backups")
def get_backups(_: str = Depends(auth.require_admin)):
    return {"settings": backup.settings(), "files": backup.list_backups()}


@router.post("/backups")
async def create_backup(_: str = Depends(auth.require_admin)):
    path, sent, clouds = await backup.run_backup("вручную")
    return {"name": path.name, "sent": sent, "clouds": clouds}


class BackupSettingsIn(BaseModel):
    enabled: bool = True
    hour: int = 4
    keep: int = 7
    telegram: bool = True


@router.put("/backups/settings")
def backup_settings(body: BackupSettingsIn, _: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    if not 0 <= body.hour <= 23 or not 1 <= body.keep <= 60:
        raise HTTPException(400, "Час 0–23, хранить 1–60 копий")
    s = settings_store.load(db)
    s["backup"] = body.model_dump()
    settings_store.save(db, s)
    return backup.settings()


@router.get("/backups/file/{name}")
def download_backup(name: str, _: str = Depends(auth.require_admin)):
    path = backup.BACKUP_DIR / name
    if not re.fullmatch(r"(nikels|nicro)-[\d-]+\.tar\.gz", name) or not path.exists():
        raise HTTPException(404, "Файл не найден")
    return Response(path.read_bytes(), media_type="application/gzip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


class RestoreIn(BaseModel):
    data_b64: str


@router.post("/backups/restore")
def restore_backup(body: RestoreIn, _: str = Depends(auth.require_admin)):
    try:
        data = base64.b64decode(body.data_b64)
        backup.schedule_restore(data)
    except Exception as e:
        raise HTTPException(400, f"Не удалось восстановить: {e}")
    return {"ok": True, "message": "Восстанавливаю — панель перезапустится через несколько секунд"}


# ---------- Xray versions / update (owner) ----------

@router.get("/xray/versions")
async def xray_versions(_: str = Depends(auth.require_admin)):
    return await updates.versions()


@router.post("/xray/update")
async def xray_update(_: str = Depends(auth.require_admin)):
    return await updates.update_all()


# ---------- alerts & probes ----------

class AlertsIn(BaseModel):
    enabled: bool = True
    cpu: int = 90
    mem: int = 90
    disk: int = 90


@router.get("/alerts")
def get_alerts(_: str = Depends(auth.require_admin)):
    return {"settings": alerts.settings(), "active": alerts.active()}


@router.put("/alerts")
def put_alerts(body: AlertsIn, _: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    s = settings_store.load(db)
    s["alerts"] = body.model_dump()
    settings_store.save(db, s)
    return alerts.settings()


@router.get("/probe")
def get_probe(_: str = Depends(auth.require_admin)):
    return probe.status()


@router.post("/probe/run")
async def run_probe(_: str = Depends(auth.require_admin)):
    return await probe.run_once()


@router.get("/expiring")
def expiring(days: int = 7, _: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    now = utcnow()
    out = []
    for u in db.scalars(select(User)):
        st = u.status(now)
        soon = u.expire_at and now < u.expire_at <= now + timedelta(days=days)
        traffic = u.data_limit and u.used >= 0.9 * u.data_limit
        if (soon or traffic or st in ("expired", "limited")) and u.enabled:
            out.append({**user_out(u, now), "reason": "expired" if st == "expired" else "limited" if st == "limited"
                        else "traffic" if traffic and not soon else "soon"})
    return sorted(out, key=lambda x: (x["expire_at"] or 1e12))


class MeIn(BaseModel):
    tg_id: str = ""


@router.patch("/auth/me")
async def update_me(body: MeIn, name: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    """Any admin sets their own Telegram ID (admin bot commands; owners also get alerts and backups)."""
    a = db.scalar(select(Admin).where(Admin.username == name))
    a.tg_id = _check_tg_id(body.tg_id)
    db.commit()
    if a.tg_id and bot.token():  # the bot's menu button in this chat now opens the panel
        await bot.admin_setup(a.tg_id)
    return {"ok": True}


class ProbeSettingsIn(BaseModel):
    enabled: bool = True
    hide_failed: bool = True


@router.put("/probe/settings")
def probe_settings(body: ProbeSettingsIn, _: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    s = settings_store.load(db)
    s["probe"] = body.model_dump()
    settings_store.save(db, s)
    return probe.settings()



# ---------- extensions (Дополнения) ----------

def _ext(db) -> dict:
    return settings_store.load(db).get("ext", {})


@router.get("/extensions")
async def extensions(_: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    """State of every switchable extension, for the Дополнения page."""
    from . import l2tp, storage
    from . import payments as payments_mod
    s = settings_store.load(db)
    ext = s.get("ext", {})
    tok = s.get("tg_bot_token", "")
    return {
        "bot": {"enabled": bool(tok), "username": bot.username},
        "mtproto": {"enabled": ext.get("mtproto", {}).get("enabled", True)},
        "probe": probe.settings(),
        "alerts": alerts.settings(),
        "backup": {**backup.settings(), "storages": len([x for x in storage.storages() if x["enabled"]])},
        "smartlink": {"enabled": ext.get("smartlink", {}).get("enabled", True)},
        "adblock": {"enabled": ext.get("adblock", {}).get("enabled", False)},
        "trial": ext.get("trial", {}),
        "l2tp": l2tp.status(),
        "payments": payments_mod.public_settings(),
        **{n: settings_store.ext(s, n) for n in ("referral", "promo", "support", "family", "routing",
                                                 "status", "failover", "report", "speed")},
        "warp": {**{k: v for k, v in settings_store.ext(s, "warp").items() if k != "account"},
                 "registered": bool(settings_store.ext(s, "warp").get("account")),
                 "default_domains": settings_store.WARP_DEFAULT_DOMAINS},
    }


# options each extension accepts from the panel
EXT_OPTIONS = {
    "trial": ("plan_id", "days", "gb"), "l2tp": ("dns",),
    "referral": ("bonus_days", "friend_days"), "routing": ("extra_direct",), "warp": ("domains",),
    "status": ("title",), "report": ("weekday", "hour"),
}


class ExtIn(BaseModel):
    enabled: bool
    options: dict = {}


@router.put("/extensions/{name}")
async def set_extension(name: str, body: ExtIn, _: str = Depends(auth.require_admin)):
    from . import l2tp
    if name not in settings_store.EXT_DEFAULTS and name != "l2tp":
        raise HTTPException(404, "Неизвестное дополнение")
    options = {k: v for k, v in body.options.items()
               if k in EXT_OPTIONS.get(name, ()) and isinstance(v, (int, float, str, list, type(None)))}
    if name == "warp" and body.enabled:
        from . import warp
        try:
            await warp.ensure_account()
        except RuntimeError as e:
            raise HTTPException(400, str(e))
    with SessionLocal() as db:
        s = settings_store.load(db)
        ext = s.setdefault("ext", {})
        cur = dict(ext.get(name, {}))
        cur.update(options)
        cur["enabled"] = body.enabled
        ext[name] = cur
        settings_store.save(db, s)
    if name == "l2tp":
        try:
            if body.enabled:
                l2tp.settings()  # generates the PSK on first use
                await l2tp.install_and_enable()
            else:
                await l2tp.disable()
        except RuntimeError as e:
            raise HTTPException(500, str(e))
    await manager.sync()
    return {"ok": True}


@router.post("/report/send")
async def send_report(_: str = Depends(auth.require_admin)):
    from . import health
    if not await health.weekly_report_if_due(force=True):
        raise HTTPException(400, "Некому отправить: подключите бота и укажите свой Telegram ID (Безопасность → Мой аккаунт)")
    return {"ok": True}


# ---------- online payments ----------

class PaymentsIn(BaseModel):
    providers: dict[str, dict] = {}
    return_url: str | None = None


@router.put("/payments/settings")
def put_payments(body: PaymentsIn, _: str = Depends(auth.require_admin)):
    from . import payments
    payments.save_settings(body.providers, body.return_url)
    return payments.public_settings()


@router.get("/payments/pending")
def pending_payments(_: str = Depends(auth.require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(Payment).where(Payment.status == "pending").order_by(Payment.id.desc()).limit(100))
    users = {u.id: u.username for u in db.scalars(select(User))}
    plans = {p.id: p.name for p in db.scalars(select(Plan))}
    return [{"id": p.id, "user_id": p.user_id, "username": users.get(p.user_id, ""), "plan": plans.get(p.plan_id, ""),
             "amount": p.amount, "provider": p.provider, "ts": ts(p.created_at)} for p in rows]


@router.post("/payments/{pid}/confirm")
async def confirm_payment(pid: int, admin: str = Depends(auth.require_admin)):
    from . import payments
    if not await payments.mark_paid(pid, admin=admin):
        raise HTTPException(400, "Платёж уже обработан или не найден")
    return {"ok": True}


@router.post("/payments/{pid}/cancel")
def cancel_payment(pid: int, _: str = Depends(auth.require_admin)):
    from . import payments
    payments.cancel(pid)
    return {"ok": True}


# ---------- cloud storages for backups ----------

@router.get("/backups/storages")
def get_storages(_: str = Depends(auth.require_admin)):
    from . import storage
    return {"catalog": storage.catalog(), "items": [storage.public(x) for x in storage.storages()]}


class StoragesIn(BaseModel):
    items: list[dict]


@router.put("/backups/storages")
def put_storages(body: StoragesIn, _: str = Depends(auth.require_admin)):
    from . import storage
    try:
        return {"items": [storage.public(x) for x in storage.save(body.items)]}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/backups/storages/{sid}/test")
async def test_storage(sid: str, _: str = Depends(auth.require_admin)):
    from . import storage
    try:
        return await storage.test(sid)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---------- broadcast through the bot ----------

class BroadcastIn(BaseModel):
    text: str
    target: str = "active"  # all | active | expiring


@router.post("/broadcast")
async def broadcast(body: BroadcastIn, _: str = Depends(auth.require_admin)):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Пустое сообщение")
    if not bot.token():
        raise HTTPException(400, "Сначала подключите Telegram-бота")
    now = utcnow()
    with SessionLocal() as db:
        users = [u for u in db.scalars(select(User).where(User.tg_id != ""))
                 if body.target == "all" or (body.target == "active" and u.status(now) == "active")
                 or (body.target == "expiring" and u.expire_at and now < u.expire_at <= now + timedelta(days=7))]
    sent = failed = 0
    for u in users:
        try:
            await bot.send(u.tg_id, f"📣 <b>nicro VPN</b>\n\n{text}")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Telegram: stay under ~30 messages/second
    return {"sent": sent, "failed": failed, "total": len(users)}
