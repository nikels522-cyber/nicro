"""Support through the bot, configurable (Поддержка → Настройки):

  mode "panel"     client messages only appear on the Поддержка page;
  mode "bot"       the main bot also forwards them to the staff (admins with a Telegram ID and a role from
                   `roles`), who answer with Reply or template buttons;
  mode "staffbot"  the same through a separate staff bot (its own token): the staff's chats stay apart from
                   the client bot.

Conversations are keyed by the client's Telegram chat: open (new client message) → answered → closed; the
first staff member who answers becomes the assignee. Replies and templates may use {name}, {link},
{expire}, {days}, {traffic_left}. The role "support" sees only this page and a read-only list of clients."""
import asyncio
import html
import logging
import re
import secrets
from datetime import timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from . import auth, settings_store
from .db import Admin, BotChat, SessionLocal, SupportMessage, User, utcnow

router = APIRouter()
log = logging.getLogger("vpnpanel.support")
GB = 1024 ** 3


def cfg() -> dict:
    with SessionLocal() as db:
        return settings_store.ext(settings_store.load(db), "support")


def _who(db, chat_id: str) -> tuple[User | None, str]:
    u = db.scalar(select(User).where(User.tg_id == chat_id))
    chat = db.get(BotChat, chat_id)
    tg = f"@{chat.tg_username}" if chat and chat.tg_username else (chat.name if chat else "")
    label = " · ".join(x for x in ((u.username if u else "без аккаунта"), tg) if x)
    return u, label


def staff_chats(c: dict | None = None) -> list[str]:
    c = c or cfg()
    with SessionLocal() as db:
        return [a.tg_id for a in db.scalars(select(Admin).where(Admin.tg_id != "", Admin.role.in_(c.get("roles") or ["owner"])))]


def is_staff(chat_id: str) -> Admin | None:
    c = cfg()
    with SessionLocal() as db:
        a = db.scalar(select(Admin).where(Admin.tg_id == chat_id))
    return a if a and (a.role in (c.get("roles") or []) or a.role == "owner") else None


def render(text: str, chat_id: str) -> str:
    """Fills {name}, {link}, {expire}, {days}, {traffic_left} for the client of this chat."""
    if "{" not in text:
        return text
    from .smartlink import url as smart_url
    with SessionLocal() as db:
        u, _ = _who(db, chat_id)
        chat = db.get(BotChat, chat_id)
        s = settings_store.load(db)
    vals = {"name": (u.username if u else "") or (chat.name if chat else "")}
    if u:
        vals["link"] = smart_url(u, s)
        if u.expire_at:
            vals["expire"] = u.expire_at.replace(tzinfo=timezone.utc).astimezone().strftime("%d.%m.%Y")
            vals["days"] = str(max((u.expire_at - utcnow()).days, 0))
        else:
            vals["expire"], vals["days"] = "∞", "∞"
        vals["traffic_left"] = f"{max(u.data_limit - u.used, 0) / GB:.1f} ГБ" if u.data_limit else "∞"
    return re.sub(r"\{(name|link|expire|days|traffic_left)\}", lambda m: vals.get(m.group(1), ""), text)


def _set_status(db, chat_id: str, status: str, assignee: str | None = None):
    chat = db.get(BotChat, chat_id) or BotChat(chat_id=chat_id)
    chat.support_status = status
    if assignee and not chat.support_assignee:  # the first one who answers takes the conversation
        chat.support_assignee = assignee
    db.merge(chat)


def _buttons(chat_id: str, c: dict) -> list[list[dict]]:
    """Template buttons + close, under every forwarded client message."""
    tpl = [{"text": "📝 " + x["title"][:28], "callback_data": f"stpl:{chat_id}:{x['id']}"} for x in c.get("templates", [])[:8]]
    rows = [tpl[i:i + 2] for i in range(0, len(tpl), 2)]
    rows.append([{"text": "✅ Закрыть обращение", "callback_data": f"sclose:{chat_id}"}])
    return rows


async def incoming(chat_id: str, text: str) -> bool:
    """A client wrote to support."""
    c = cfg()
    with SessionLocal() as db:
        u, label = _who(db, chat_id)
        m = SupportMessage(chat_id=chat_id, user_id=u.id if u else None, direction="in", text=text[:4000])
        db.add(m)
        _set_status(db, chat_id, "open")
        db.commit()
        mid = m.id
    if c.get("autoreply"):
        try:
            from .telegram import bot
            await bot.send(chat_id, html.escape(render(c["autoreply"], chat_id)))
        except Exception:
            pass
    mode = c.get("mode", "bot")
    if mode == "panel":
        return True
    if mode == "staffbot":
        sender = staff_bot
    else:
        from .telegram import bot as sender
    msg = (f"💬 <b>Поддержка</b> · {html.escape(label)}\n\n{html.escape(text[:3500])}\n\n"
           "<i>Ответьте на это сообщение (Reply) или выберите шаблон.</i>")
    refs = {}
    for a in staff_chats(c):
        try:
            res = await sender.call("sendMessage", chat_id=a, text=msg, parse_mode="HTML",
                                    reply_markup={"inline_keyboard": _buttons(chat_id, c)})
            refs[a] = res["message_id"]
        except Exception as e:
            log.warning("support forward to %s failed: %s", a, e)
    with SessionLocal() as db:
        db.get(SupportMessage, mid).tg_refs = refs
        db.commit()
    return True


def chat_for_reply(admin_chat: str, reply_to_id: int) -> str | None:
    """Which client's message did a staff member reply to in Telegram?"""
    with SessionLocal() as db:
        for m in db.scalars(select(SupportMessage).where(SupportMessage.direction == "in")
                            .order_by(SupportMessage.id.desc()).limit(1000)):
            if (m.tg_refs or {}).get(admin_chat) == reply_to_id:
                return m.chat_id
    return None


async def answer(chat_id: str, text: str, admin: str):
    """Sends a staff reply to the client (through the main bot) and records it."""
    from .i18n import chat_lang, t
    from .telegram import bot
    text = render(text, chat_id)
    await bot.send(chat_id, t(chat_lang(chat_id), "💬 <b>Поддержка nicro</b>") + f"\n\n{html.escape(text)}")
    with SessionLocal() as db:
        u, _ = _who(db, chat_id)
        db.add(SupportMessage(chat_id=chat_id, user_id=u.id if u else None, direction="out", text=text[:4000],
                              admin=admin, read=True))
        for m in db.scalars(select(SupportMessage).where(SupportMessage.chat_id == chat_id, ~SupportMessage.read)):
            m.read = True
        _set_status(db, chat_id, "answered", admin)
        db.commit()


def set_status(chat_id: str, status: str, admin: str = ""):
    with SessionLocal() as db:
        _set_status(db, chat_id, status, admin or None)
        if status == "closed":
            for m in db.scalars(select(SupportMessage).where(SupportMessage.chat_id == chat_id, ~SupportMessage.read)):
                m.read = True
        db.commit()


def unread() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(SupportMessage).where(
            SupportMessage.direction == "in", ~SupportMessage.read)) or 0


# ------------------------------------------------------------------ staff actions from Telegram

async def staff_callback(admin: Admin, data: str) -> str | None:
    """Template / close buttons pressed by a staff member (in the main bot or the staff bot)."""
    kind, _, rest = data.partition(":")
    chat_id, _, tpl_id = rest.partition(":")
    if kind == "sclose":
        set_status(chat_id, "closed", admin.username)
        return "✅ Обращение закрыто."
    if kind == "stpl":
        tpl = next((x for x in cfg().get("templates", []) if x["id"] == tpl_id), None)
        if not tpl:
            return "Шаблон не найден — обновите список в панели."
        await answer(chat_id, tpl["text"], admin.username)
        return f"✅ Отправлен шаблон «{tpl['title']}»."
    return None


async def staff_reply(admin: Admin, admin_chat: str, reply_to_id: int, text: str) -> bool:
    client = chat_for_reply(admin_chat, reply_to_id)
    if not client:
        return False
    await answer(client, text, admin.username)
    return True


class StaffBot:
    """The separate bot for the support staff (mode "staffbot"): delivers client messages, takes replies."""

    def __init__(self):
        self.username: str | None = None
        self._token = ""
        self._offset = 0

    @staticmethod
    def token() -> str:
        c = cfg()
        return c.get("staff_bot_token", "") if c.get("mode") == "staffbot" else ""

    async def call(self, method: str, **params) -> dict:
        token = self.token()
        if not token:
            raise RuntimeError("Бот поддержки не настроен")
        from .config import http
        r = await http().post(f"https://api.telegram.org/bot{token}/{method}", json=params)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "Ошибка Telegram"))
        return data["result"]

    async def send(self, chat_id: str, text: str):
        await self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML")

    async def _handle(self, upd: dict):
        if "callback_query" in upd:
            cq = upd["callback_query"]
            chat = str(cq.get("message", {}).get("chat", {}).get("id", ""))
            try:
                await self.call("answerCallbackQuery", callback_query_id=cq["id"])
            except Exception:
                pass
            admin = is_staff(chat)
            if admin:
                note = await staff_callback(admin, cq.get("data", ""))
                if note:
                    await self.send(chat, html.escape(note))
            return
        msg = upd.get("message") or {}
        chat = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not chat or not text:
            return
        admin = is_staff(chat)
        if not admin:
            await self.send(chat, f"Это бот поддержки nicro для персонала. Ваш Telegram ID: <code>{chat}</code> — "
                                  "попросите владельца указать его в вашей учётной записи панели.")
            return
        reply_to = msg.get("reply_to_message")
        if reply_to and await staff_reply(admin, chat, reply_to.get("message_id"), text):
            await self.send(chat, "✅ Ответ отправлен клиенту.")
        else:
            await self.send(chat, "Чтобы ответить клиенту, нажмите «Ответить» (Reply) на его сообщение "
                                  "или выберите шаблон под ним.")

    async def loop(self):
        while True:
            token = self.token()
            if not token:
                self.username = None
                await asyncio.sleep(15)
                continue
            try:
                if token != self._token:
                    self.username = (await self.call("getMe"))["username"]
                    self._token, self._offset = token, 0
                updates = await self.call("getUpdates", offset=self._offset, timeout=25,
                                          allowed_updates=["message", "callback_query"])
                for upd in updates:
                    self._offset = upd["update_id"] + 1
                    try:
                        await self._handle(upd)
                    except Exception:
                        log.exception("staff bot update failed")
            except Exception as e:
                log.warning("staff bot: %s", e)
                await asyncio.sleep(15)


staff_bot = StaffBot()


# ------------------------------------------------------------------ panel API

def _thread_row(db, chat_id: str) -> dict:
    u, label = _who(db, chat_id)
    chat = db.get(BotChat, chat_id)
    return {"chat_id": chat_id, "label": label, "user_id": u.id if u else None,
            "status": (chat.support_status if chat else "") or "open", "assignee": chat.support_assignee if chat else ""}


@router.get("/support")
def threads(status: str = "", _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        rows = list(db.scalars(select(SupportMessage).order_by(SupportMessage.id.desc()).limit(3000)))
        out: dict[str, dict] = {}
        for m in rows:
            th = out.get(m.chat_id)
            if th is None:
                th = out[m.chat_id] = {**_thread_row(db, m.chat_id), "last": m.text[:140], "last_dir": m.direction,
                                       "ts": int(m.ts.timestamp()), "unread": 0}
            if m.direction == "in" and not m.read:
                th["unread"] += 1
    items = [x for x in out.values()
             if not status or (x["status"] != "closed" if status == "active" else x["status"] == status)]
    return {"threads": items, "unread": sum(x["unread"] for x in out.values()),
            "open": sum(1 for x in out.values() if x["status"] == "open")}


@router.get("/support/unread")
def unread_count(_: str = Depends(auth.require_admin)):
    """Cheap counter for the menu badge (polled by every open panel)."""
    return {"unread": unread()}


@router.get("/support/templates")
def templates(_: str = Depends(auth.require_admin)):
    return cfg().get("templates", [])


def settings_out() -> dict:
    c = cfg()
    tok = c.get("staff_bot_token", "")
    with SessionLocal() as db:
        staff = [{"username": a.username, "role": a.role, "tg": bool(a.tg_id)} for a in db.scalars(select(Admin))]
    return {**{k: v for k, v in c.items() if k != "staff_bot_token"},
            "staff_bot_token": f"{tok[:6]}…{tok[-4:]}" if tok else "", "staff_bot": staff_bot.username, "staff": staff}


@router.get("/support/settings")
def get_settings(_: str = Depends(auth.require_admin)):
    return settings_out()


class SupportSettingsIn(BaseModel):
    enabled: bool = True
    mode: str = "bot"
    staff_bot_token: str | None = None  # None or the masked value keeps the saved token
    roles: list[str] = ["owner", "operator", "support"]
    autoreply: str = ""
    templates: list[dict] = []


@router.put("/support/settings")
async def put_settings(body: SupportSettingsIn, _: str = Depends(auth.require_admin)):
    if body.mode not in ("panel", "bot", "staffbot"):
        raise HTTPException(400, "Неизвестный режим")
    tpls = []
    for x in body.templates[:50]:
        title, text = str(x.get("title", "")).strip()[:40], str(x.get("text", "")).strip()[:2000]
        if title and text:
            tpls.append({"id": str(x.get("id") or "t" + secrets.token_hex(3))[:16], "title": title, "text": text})
    with SessionLocal() as db:
        cur = settings_store.ext(settings_store.load(db), "support")
    token = cur.get("staff_bot_token", "")
    if body.staff_bot_token is not None and "…" not in body.staff_bot_token:
        token = body.staff_bot_token.strip()
        if token:
            try:
                async with httpx.AsyncClient(timeout=20) as c:
                    r = (await c.get(f"https://api.telegram.org/bot{token}/getMe")).json()
                if not r.get("ok"):
                    raise ValueError(r.get("description"))
            except Exception as e:
                raise HTTPException(400, f"Токен бота поддержки не подходит: {e}")
    if body.mode == "staffbot" and not token:
        raise HTTPException(400, "Для режима «отдельный бот» укажите токен бота поддержки")
    with SessionLocal() as db:
        s = settings_store.load(db)
        s.setdefault("ext", {})["support"] = {
            "enabled": body.enabled, "mode": body.mode, "staff_bot_token": token,
            "roles": [r for r in body.roles if r in auth.ROLE_NAMES] or ["owner"],
            "autoreply": body.autoreply.strip()[:1000], "templates": tpls}
        settings_store.save(db, s)
    return settings_out()


@router.get("/support/{chat_id}")
def thread(chat_id: str, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        info = _thread_row(db, chat_id)
        msgs = list(db.scalars(select(SupportMessage).where(SupportMessage.chat_id == chat_id)
                               .order_by(SupportMessage.id.desc()).limit(300)))
    return {**info, "messages": [{"id": m.id, "dir": m.direction, "text": m.text, "admin": m.admin,
                                  "ts": int(m.ts.timestamp())} for m in reversed(msgs)]}


class ReplyIn(BaseModel):
    text: str


@router.post("/support/{chat_id}")
async def reply(chat_id: str, body: ReplyIn, admin: str = Depends(auth.require_admin)):
    if not body.text.strip():
        raise HTTPException(400, "Пустой ответ")
    try:
        await answer(chat_id, body.text.strip(), admin)
    except Exception as e:
        raise HTTPException(400, f"Не удалось отправить: {e}")
    return {"ok": True}


class StatusIn(BaseModel):
    status: str


@router.post("/support/{chat_id}/status")
def change_status(chat_id: str, body: StatusIn, admin: str = Depends(auth.require_admin)):
    if body.status not in ("open", "answered", "closed"):
        raise HTTPException(400, "Неизвестный статус")
    set_status(chat_id, body.status, admin)
    return {"ok": True}


@router.post("/support/{chat_id}/assign")
def assign(chat_id: str, admin: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        chat = db.get(BotChat, chat_id) or BotChat(chat_id=chat_id)
        chat.support_assignee = admin
        db.merge(chat)
        db.commit()
    return {"ok": True}


@router.post("/support/{chat_id}/read")
def mark_read(chat_id: str, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        for m in db.scalars(select(SupportMessage).where(SupportMessage.chat_id == chat_id, ~SupportMessage.read)):
            m.read = True
        db.commit()
    return {"ok": True}


def touch_chat(chat_id: str, sender: dict):
    """Remembers everyone who writes to the bot (name for support, referral arrival, language)."""
    with SessionLocal() as db:
        chat = db.get(BotChat, chat_id) or BotChat(chat_id=chat_id)
        chat.name = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x)[:128]
        chat.tg_username = (sender.get("username") or "")[:64]
        chat.last_at = utcnow()
        if not chat.lang:  # first contact: language from the Telegram app (the client may change it with /lang)
            from .i18n import pick
            chat.lang = pick(sender.get("language_code"))
        db.merge(chat)
        db.commit()
