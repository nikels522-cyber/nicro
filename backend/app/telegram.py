"""Telegram bot: tells clients their chat ID (/start), shows their status (/status) and notifies
them before the subscription ends and when traffic runs out. The token is set in the panel."""
import asyncio
import hashlib
import hmac
import html
import logging
import re
from urllib.parse import urlparse
from datetime import timedelta, timezone

import httpx
from sqlalchemy import select

from . import config, settings_store
from .db import Admin, SessionLocal, User, utcnow
from .i18n import chat_lang, t
from .links import sub_url

log = logging.getLogger("vpnpanel.telegram")
GB = 1024 ** 3
CHECK_INTERVAL = 300  # seconds between notification checks
EXPIRY_WARN_DAYS = 3


def _gb(n: int, lang: str = "ru") -> str:
    return t(lang, "{n} ГБ", n=f"{n / GB:.1f}")


def _date(dt) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone().strftime("%d.%m.%Y")


def status_text(u: User, lang: str = "ru") -> str:
    L = lang
    lines = [f"🛡 <b>nicro VPN</b> · {html.escape(u.username)}"]
    st = u.status()
    lines.append(t(L, {"active": "✅ Подписка активна", "expired": "⛔ Подписка закончилась",
                       "limited": "⛔ Трафик закончился", "disabled": "⛔ Доступ отключён"}[st]))
    if u.data_limit:
        left = max(u.data_limit - u.used, 0)
        lines.append(t(L, "📊 Трафик: {used} из {limit} (осталось {left})",
                       used=_gb(u.used, L), limit=_gb(u.data_limit, L), left=_gb(left, L)))
    else:
        lines.append(t(L, "📊 Трафик: {used} (без ограничений)", used=_gb(u.used, L)))
    if u.expire_at:
        days = (u.expire_at - utcnow()).days
        lines.append(t(L, "📅 Действует до {date}", date=_date(u.expire_at)) +
                     (t(L, " (осталось {days} дн.)", days=days) if days >= 0 else ""))
    else:
        lines.append(t(L, "📅 Бессрочно"))
    return "\n".join(lines)


def due_notifications(u: User, L: str = "ru") -> list[tuple[str, str]]:
    """(key, text) of notifications this user should get now and hasn't got yet. Keys encode the
    expiry date / limit, so extending the subscription or resetting traffic re-arms them."""
    now = utcnow()
    sent = u.notified or {}
    out = []
    if u.expire_at:
        left = u.expire_at - now
        exp = int(u.expire_at.replace(tzinfo=timezone.utc).timestamp())
        if left.total_seconds() <= 0:
            out.append((f"expired:{exp}", t(L, "⛔ <b>Ваша подписка на VPN закончилась.</b>\nПродлить: /buy — или напишите в поддержку.")))
        elif left.days < EXPIRY_WARN_DAYS:
            days = max(left.days, 0) + (1 if left.seconds else 0)
            out.append((f"exp3:{exp}", t(L, "⏳ <b>Подписка на VPN заканчивается через {days} дн.</b> — {date}.\nПродлите её заранее, чтобы не остаться без доступа. /buy",
                                         days=days, date=_date(u.expire_at))))
    if u.data_limit:
        pct = u.used / u.data_limit
        if pct >= 1:
            out.append((f"t100:{u.data_limit}", t(L, "⛔ <b>Трафик закончился</b> ({limit}).\nДоступ приостановлен — продлите подписку (/buy) или напишите в поддержку.",
                                                  limit=_gb(u.data_limit, L))))
        elif pct >= 0.9:
            out.append((f"t90:{u.data_limit}", t(L, "⚠️ <b>Израсходовано {pct} трафика</b>: {used} из {limit}.\nОсталось {left}.",
                                                 pct=f"{pct:.0%}", used=_gb(u.used, L), limit=_gb(u.data_limit, L),
                                                 left=_gb(u.data_limit - u.used, L))))
    return [(k, t) for k, t in out if k not in sent]


class TelegramBot:
    def __init__(self):
        self.username: str | None = None
        self._token: str = ""
        self._offset = 0

    @staticmethod
    def token() -> str:
        with SessionLocal() as db:
            return settings_store.load(db).get("tg_bot_token", "")

    async def call(self, method: str, token: str | None = None, **params) -> dict:
        token = token or self.token()
        if not token:
            raise RuntimeError("Токен бота не задан")
        r = await config.http().post(f"https://api.telegram.org/bot{token}/{method}", json=params)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "Ошибка Telegram"))
        return data["result"]

    async def send(self, chat_id: str, text: str, buttons: list[list[dict]] | None = None) -> None:
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        await self.call("sendMessage", **params)

    async def send_document(self, chat_id: str, path, caption: str = "") -> None:
        token = self.token()
        if not token:
            raise RuntimeError("Токен бота не задан")
        async with httpx.AsyncClient(timeout=120) as c:
            with open(path, "rb") as f:
                r = await c.post(f"https://api.telegram.org/bot{token}/sendDocument",
                                 data={"chat_id": chat_id, "caption": caption[:1000]},
                                 files={"document": (path.name, f, "application/gzip")})
        if not r.json().get("ok"):
            raise RuntimeError(r.json().get("description", "Ошибка Telegram"))

    async def send_admins(self, text: str, roles: tuple[str, ...] = ("owner",)) -> int:
        """Alerts etc. to admins who set their Telegram ID (Безопасность → Администраторы)."""
        with SessionLocal() as db:
            chats = [a.tg_id for a in db.scalars(select(Admin).where(Admin.tg_id != "", Admin.role.in_(roles)))]
        sent = 0
        for chat in chats:
            try:
                await self.send(chat, text)
                sent += 1
            except Exception as e:
                log.warning("admin message to %s failed: %s", chat, e)
        return sent

    async def send_subscription(self, u: User) -> None:
        """Subscription link + how to connect, with buttons to the client page (apps, QR)."""
        with SessionLocal() as db:
            s = settings_store.load(db)
        from .smartlink import url as smart_url
        L = chat_lang(u.tg_id)
        url = smart_url(u, s) + f"?lang={L}"
        text = (f"🛡 <b>nicro VPN · {html.escape(u.username)}</b>\n\n" +
                t(L, "<b>Как подключиться:</b>\n1. Установите приложение: <b>Happ</b> (Android/iPhone) или <b>v2RayTun</b>.\n"
                     "2. Нажмите «Подключить» ниже — откроется страница под ваше устройство с кнопкой добавления.\n"
                     "   Или скопируйте ссылку и вставьте в приложении через «+» → «Из буфера».") +
                f"\n\n<code>{html.escape(smart_url(u, s))}</code>\n\n" + status_text(u, L))
        from .botflows import menu
        rows = [[{"text": t(L, "📲 Подключить"), "url": url}]] + [r for r in menu(u.tg_id) if r[0].get("callback_data") != "sub"]
        await self.send(u.tg_id, text, rows)

    async def admin_setup(self, chat_id: str):
        """An admin's chat: the bot's menu button opens the panel (Telegram mini app) and the command list
        shows the admin commands. Clients keep the default menu."""
        url = panel_url()
        try:
            await self.call("setChatMenuButton", chat_id=chat_id,
                            menu_button={"type": "web_app", "text": "nicro", "web_app": {"url": url}})
            await self.call("setMyCommands", scope={"type": "chat", "chat_id": chat_id}, commands=[
                {"command": c, "description": d} for c, d in ADMIN_COMMANDS])
        except Exception as e:
            log.warning("admin menu for %s: %s", chat_id, e)

    async def setup_admins(self):
        with SessionLocal() as db:
            chats = [a.tg_id for a in db.scalars(select(Admin).where(Admin.tg_id != ""))]
        for c in chats:
            await self.admin_setup(c)

    async def check_token(self, token: str) -> str:
        me = await self.call("getMe", token=token)
        return me["username"]

    # ---- incoming updates (long polling); client flows live in botflows.py ----

    async def _handle(self, msg: dict):
        from . import botflows, growth, support
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if not chat_id or msg.get("chat", {}).get("type", "private") != "private":
            return
        sender = msg.get("from", {})
        support.touch_chat(chat_id, sender)
        if msg.get("successful_payment"):
            await botflows.on_successful_payment(msg)
            return
        text = (msg.get("text") or "").strip()
        if not text:
            return
        if not text.startswith("/"):
            if not await botflows.on_text(msg):
                await self.send(chat_id, ADMIN_HELP)
            return
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.split("@")[0].lower(), arg.strip()
        L = chat_lang(chat_id)
        if cmd in ("/lang", "/language"):
            from .i18n import lang_buttons
            await self.send(chat_id, "🌐 Язык / Language", lang_buttons())
            return
        if cmd == "/start" and arg.startswith("inv_"):  # invite link from the panel: bind this chat
            u = bind_invite(arg, chat_id)
            if u:
                await self.send(chat_id, t(L, "✅ Telegram привязан — буду присылать напоминания об оплате и трафике."),
                                botflows.menu(chat_id))
                await self.send_subscription(u)
            else:
                await self.send(chat_id, t(L, "Ссылка-приглашение недействительна. Попросите администратора новую."))
            return
        if cmd == "/start" and arg.startswith("ref_"):
            inviter = growth.remember_arrival(chat_id, arg[4:])
            if inviter:
                log.info("referral arrival %s from %s", chat_id, inviter.username)
            arg = ""
        with SessionLocal() as db:
            admin = db.scalar(select(Admin).where(Admin.tg_id == chat_id))
        client_cmds = ("/buy", "/promo", "/ref", "/support", "/trial", "/menu")
        if admin and cmd not in client_cmds and not (cmd == "/start" and arg):
            text = await admin_command(admin, cmd, arg)
            if cmd in ("/start", "/help", "/panel", "/app"):  # the panel itself, one tap away
                await self.admin_setup(chat_id)
                await self.send(chat_id, text, panel_buttons())
            else:
                await self.send(chat_id, text)
            return
        users = [u for u in botflows._users(chat_id)]
        if cmd == "/trial":
            await botflows.client_action(chat_id, "trial", "", sender)
        elif cmd == "/buy":
            await botflows.show_plans(chat_id)
        elif cmd == "/promo":
            await botflows.promo_command(chat_id, arg)
        elif cmd == "/ref":
            await botflows.send_ref(chat_id)
        elif cmd == "/support":
            if arg:
                await support.incoming(chat_id, arg)
                await self.send(chat_id, t(L, "✉️ Передал в поддержку — ответ придёт сюда."))
            else:
                await botflows.client_action(chat_id, "support", "", sender)
        elif users and cmd == "/sub":
            for u in users:
                await self.send_subscription(u)
        elif users:
            await self.send(chat_id, "\n\n".join(status_text(u, L) for u in users), botflows.menu(chat_id))
        else:
            reply = t(L, "👋 Здравствуйте! Это бот nicro VPN.\n\nЕсли у вас уже есть доступ, <b>пришлите сюда свою ссылку-подписку</b> "
                         "или любой ключ vless://… (в приложении: профиль → поделиться / скопировать) — я узнаю ваш аккаунт.\n\n"
                         "Ваш Telegram ID: <code>{chat_id}</code>\n🌐 /lang — Language", chat_id=chat_id)
            await self.send(chat_id, reply, botflows.menu(chat_id) or None)

    async def poll_loop(self):
        from . import botflows
        while True:
            token = self.token()
            if not token:
                self.username = None
                await asyncio.sleep(15)
                continue
            try:
                if token != self._token:  # new token: identify the bot, drop the old queue position
                    self.username = await self.check_token(token)
                    self._token, self._offset = token, 0
                    await self.setup_admins()
                updates = await self.call("getUpdates", offset=self._offset, timeout=25,
                                          allowed_updates=["message", "callback_query", "pre_checkout_query"])
                for upd in updates:
                    self._offset = upd["update_id"] + 1
                    try:
                        if "message" in upd:
                            await self._handle(upd["message"])
                        elif "callback_query" in upd:
                            await botflows.on_callback(upd["callback_query"])
                        elif "pre_checkout_query" in upd:
                            await botflows.on_pre_checkout(upd["pre_checkout_query"])
                    except Exception:
                        log.exception("telegram update failed")
            except Exception as e:
                log.warning("telegram polling: %s", e)
                await asyncio.sleep(15)

    # ---- outgoing notifications ----

    async def notify_once(self):
        if not self.token():
            return
        with SessionLocal() as db:
            users = list(db.scalars(select(User).where(User.tg_id != "")))
            for u in users:
                if not u.enabled:
                    continue
                for key, text in due_notifications(u, chat_lang(u.tg_id)):
                    try:
                        await self.send(u.tg_id, text)
                    except Exception as e:
                        log.warning("notify %s failed: %s", u.username, e)
                        continue
                    u.notified = {**(u.notified or {}), key: int(utcnow().timestamp())}
                    log.info("notified %s: %s", u.username, key)
            db.commit()

    async def notify_loop(self):
        await asyncio.sleep(30)
        while True:
            try:
                await self.notify_once()
            except Exception:
                log.exception("notification check failed")
            await asyncio.sleep(CHECK_INTERVAL)


bot = TelegramBot()


# ------------------------------------------------------------------ invites

def invite_code(u: User) -> str:
    sig = hmac.new(config.JWT_SECRET.encode(), f"inv:{u.id}:{u.sub_token}".encode(), hashlib.sha256).hexdigest()[:12]
    return f"inv_{u.id}_{sig}"


def invite_link(u: User) -> str | None:
    return f"https://t.me/{bot.username}?start={invite_code(u)}" if bot.username else None


def bind(u: User, chat_id: str):
    with SessionLocal() as db:
        db.get(User, u.id).tg_id = chat_id
        db.commit()
    u.tg_id = chat_id


def find_by_key(text: str) -> User | None:
    from .botflows import find_by_key as _find
    return _find(text)


def bind_invite(code: str, chat_id: str) -> User | None:
    try:
        _, uid, _sig = code.split("_", 2)
        with SessionLocal() as db:
            u = db.get(User, int(uid))
            if not u or not hmac.compare_digest(invite_code(u), code):
                return None
            u.tg_id = chat_id
            db.commit()
            return u
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------ admin commands

ADMIN_COMMANDS = [("panel", "Открыть панель (приложение)"), ("server", "Состояние серверов"),
                  ("users", "Сводка по клиентам"), ("expiring", "Истекают в ближайшие 7 дней"),
                  ("find", "Найти клиента: /find имя"), ("add", "Создать клиента: /add имя 30д 50гб"),
                  ("extend", "Продлить: /extend имя 30д"), ("sub", "Ссылка клиента: /sub имя"),
                  ("backup", "Прислать бэкап"), ("help", "Все команды")]


def panel_url() -> str:
    with SessionLocal() as db:
        s = settings_store.load(db)
    base = f"https://{s['panel_domain']}:{urlparse(s['sub_base_url']).port or 2053}" if s.get("panel_domain") \
        else s["sub_base_url"].rstrip("/")
    return f"{base}/{config.PANEL_PATH}/"


def panel_buttons() -> list[list[dict]]:
    url = panel_url()
    return [[{"text": "📱 Открыть в Telegram", "web_app": {"url": url}}],
            [{"text": "🌐 Открыть в браузере", "url": url}]]


ADMIN_HELP = ("🛡 <b>nicro — команды администратора</b>\n"
              "/panel — открыть панель (кнопка «nicro» внизу тоже открывает её)\n"
              "/server — состояние серверов\n"
              "/users — сводка по клиентам\n"
              "/expiring — истекают в ближайшие 7 дней\n"
              "/find имя — найти клиента\n"
              "/add имя [тариф | 30д] [50гб] — создать клиента\n"
              "/extend имя [тариф | 30д] [50гб] — продлить\n"
              "/sub имя — ссылка и приглашение клиента\n"
              "/backup — прислать бэкап\n\n"
              "📱 <b>Панель как приложение на телефоне</b>: откройте её в браузере → Android: меню ⋮ → "
              "«Установить приложение»; iPhone (Safari): «Поделиться» → «На экран „Домой“».")


def _parse_terms(tokens: list[str]):
    """'30д'/'30d' -> days, '50гб'/'50gb' -> gb, anything else -> plan name."""
    days = gb = 0
    rest = []
    for t in tokens:
        m = re.fullmatch(r"(\d+)\s*(д|d|дн|days?)", t.lower())
        g = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(гб|gb|g)", t.lower())
        if m:
            days = int(m.group(1))
        elif g:
            gb = float(g.group(1).replace(",", "."))
        else:
            rest.append(t)
    return days, gb, " ".join(rest)


def _find_plan(db, name: str):
    from .db import Plan
    if not name:
        return None
    plans = list(db.scalars(select(Plan).where(Plan.active)))
    return next((p for p in plans if p.name.lower() == name.lower()), None) or \
        next((p for p in plans if p.name.lower().startswith(name.lower())), None)


async def admin_command(admin: Admin, cmd: str, arg: str) -> str:
    from . import auth, billing
    from .api import _new_secrets, USERNAME_RE
    from .cores.devices import devices
    from .cores.manager import manager
    from .monitor import monitor
    write = cmd in ("/add", "/extend")
    if write and not auth.allowed(admin.role, "POST", "/users"):
        return "Недостаточно прав для этой команды."
    if cmd in ("/help", "/start", "/panel", "/app"):
        return ADMIN_HELP
    if cmd == "/server":
        from .cluster import enabled_nodes, flag
        from .relays import relay_monitor
        m = monitor.latest
        lines = [f"🖥 <b>Главный</b>: CPU {m.get('cpu', 0)}%, RAM {m.get('mem_used', 0) / GB:.1f}/"
                 f"{m.get('mem_total', 1) / GB:.1f} ГБ, ↓{m.get('net_rx_rate', 0) / 1e6 * 8:.1f} Мбит/с"]
        for r in relay_monitor.summary():
            lines.append(f"{'🟢' if r['online'] else '🔴'} Точка входа {r['name']}")
        now = utcnow()
        for n in enabled_nodes():
            ok = n.last_seen and (now - n.last_seen).total_seconds() < 30
            lines.append(f"{'🟢' if ok else '🔴'} {flag(n.country)} {n.name}")
        return "\n".join(lines)
    with SessionLocal() as db:
        if cmd == "/users":
            now = utcnow()
            users = list(db.scalars(select(User)))
            st = [u.status(now) for u in users]
            online = sum(1 for u in users if devices.online_count(u.username))
            return (f"👥 Клиентов: {len(users)} · активных {st.count('active')} · онлайн {online}\n"
                    f"⛔ истёк срок: {st.count('expired')} · лимит: {st.count('limited')} · отключены: {st.count('disabled')}")
        if cmd == "/expiring":
            now = utcnow()
            soon = sorted((u for u in db.scalars(select(User)) if u.expire_at and now < u.expire_at <= now + timedelta(days=7)),
                          key=lambda u: u.expire_at)
            return "\n".join(f"⏳ {html.escape(u.username)} — {_date(u.expire_at)}" for u in soon) or "Никто не истекает в ближайшие 7 дней."
        if cmd == "/backup":
            if admin.role != "owner":
                return "Бэкап доступен только владельцу."
            from .backup import run_backup
            path, _, _ = await run_backup("по команде")
            try:
                await bot.send_document(admin.tg_id, path, f"🗄 {path.name}")
            except Exception as e:
                return f"Бэкап создан ({path.name}), но отправить не удалось: {e}"
            return "Готово."
        parts = arg.split()
        if not parts:
            return ADMIN_HELP
        name = parts[0]
        u = db.scalar(select(User).where(User.username == name))
        if cmd == "/find":
            found = [x for x in db.scalars(select(User)) if name.lower() in x.username.lower()][:10]
            return "\n\n".join(status_text(x) for x in found) or "Не найдено."
        if cmd == "/sub":
            if not u:
                return "Клиент не найден."
            inv = invite_link(u)
            with SessionLocal() as db2:
                s = settings_store.load(db2)
            return (f"🔗 <code>{html.escape(sub_url(u, s))}</code>" +
                    (f"\n\n📨 Приглашение в бота (перешлите клиенту):\n{inv}" if inv else ""))
        days, gb, plan_name = _parse_terms(parts[1:])
        plan = _find_plan(db, plan_name)
        if plan_name and not plan:
            return f"Тариф «{html.escape(plan_name)}» не найден."
        if cmd == "/add":
            if u:
                return "Такой клиент уже есть."
            if not USERNAME_RE.match(name):
                return "Имя: 2–32 символа, латиница, цифры, _ . -"
            u = User(username=name, data_limit=int(gb * GB),
                     expire_at=utcnow() + timedelta(days=days) if days else None, **_new_secrets())
            db.add(u)
            db.flush()
            if plan:
                billing.apply_plan(u, plan)
            billing.record(db, u, plan, plan.price if plan else 0, "создан через Telegram", admin.username)
        elif cmd == "/extend":
            if not u:
                return "Клиент не найден."
            if plan:
                billing.apply_plan(u, plan)
            elif days or gb:
                billing.extend(u, days, gb)
            else:
                return "Укажите тариф или срок: /extend имя 30д"
            billing.record(db, u, plan, plan.price if plan else 0, "продлён через Telegram", admin.username)
        else:
            return ADMIN_HELP
        db.commit()
        text = status_text(u)
        inv = invite_link(u)
        s = settings_store.load(db)
        link = sub_url(u, s)
    await manager.sync()
    return (("✅ Клиент создан\n\n" if cmd == "/add" else "✅ Продлено\n\n") + text +
            f"\n\n🔗 <code>{html.escape(link)}</code>" + (f"\n📨 Приглашение: {inv}" if inv and cmd == "/add" else ""))



# ------------------------------------------------------------------ trial (extension)

def trial_settings() -> dict:
    with SessionLocal() as db:
        return settings_store.load(db).get("ext", {}).get("trial", {})


async def start_trial(chat_id: str, sender: dict, has_account: bool) -> str:
    from . import billing
    from .api import _new_secrets
    from .cores.manager import manager
    from .db import Plan
    cfg = trial_settings()
    L = chat_lang(chat_id)
    if not cfg.get("enabled"):
        return t(L, "Пробный период сейчас не выдаётся. Напишите в поддержку.")
    if has_account:
        return t(L, "У вас уже есть аккаунт — пробный период выдаётся один раз. /sub — ссылка для подключения.")
    name = f"t{chat_id}".replace("-", "")[:32]
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == name)):
            return t(L, "Пробный период уже был выдан этому Telegram-аккаунту.")
        who = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x)
        uname = f" @{sender['username']}" if sender.get("username") else ""
        u = User(username=name, tg_id=chat_id, multi_device=False, note=f"пробный период: {who}{uname}".strip(),
                 data_limit=int(float(cfg.get("gb") or 0) * GB),
                 expire_at=utcnow() + timedelta(days=int(cfg.get("days") or 1)), **_new_secrets())
        db.add(u)
        db.flush()
        plan = db.get(Plan, cfg["plan_id"]) if cfg.get("plan_id") else None
        if plan:
            billing.apply_plan(u, plan)
        billing.record(db, u, plan, 0, "пробный период (Telegram)", "бот")
        db.commit()
    await manager.sync()
    await bot.send_admins(f"🎁 <b>nicro:</b> выдан пробный период {html.escape(name)}{html.escape(uname)}",
                          roles=("owner", "operator"))
    return t(L, "🎁 Пробный период активирован! Ниже — как подключиться.")
