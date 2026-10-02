"""Client-side bot flows: menu, purchase, promo codes, referral, support, binding by key or name,
admin confirmation buttons and Telegram Stars payments. telegram.py routes updates here."""
import html
import logging
import re

from sqlalchemy import select

from . import growth, payments, settings_store, support
from .db import Admin, Payment, Plan, SessionLocal, User, utcnow
from .i18n import chat_lang, t

log = logging.getLogger("vpnpanel.bot")
USER_RE = re.compile(r"^[A-Za-z0-9_.-]{2,32}$")


def _bot():
    from .telegram import bot
    return bot


def _settings() -> dict:
    with SessionLocal() as db:
        return settings_store.load(db)


def _users(chat_id: str) -> list[User]:
    with SessionLocal() as db:
        return list(db.scalars(select(User).where(User.tg_id == chat_id).order_by(User.id)))


def _admin(chat_id: str) -> Admin | None:
    with SessionLocal() as db:
        return db.scalar(select(Admin).where(Admin.tg_id == chat_id))


def _plans() -> list[Plan]:
    with SessionLocal() as db:
        return list(db.scalars(select(Plan).where(Plan.active, Plan.price > 0).order_by(Plan.sort, Plan.id)))


def menu(chat_id: str) -> list[list[dict]]:
    s = _settings()
    has = bool(_users(chat_id))
    ext = lambda n: settings_store.ext(s, n)  # noqa: E731
    L = chat_lang(chat_id)
    rows = []
    if has:
        rows.append([{"text": t(L, "📲 Подключить"), "callback_data": "sub"}, {"text": t(L, "📊 Статус"), "callback_data": "status"}])
    if payments.enabled() and _plans():
        rows.append([{"text": t(L, "💳 Оплатить / продлить") if has else t(L, "💳 Купить доступ"), "callback_data": "buy"}])
    if not has and ext("trial")["enabled"]:
        rows.append([{"text": t(L, "🎁 Пробный период"), "callback_data": "trial"}])
    extra = []
    if has and ext("referral")["enabled"]:
        extra.append({"text": t(L, "🤝 Пригласить друга"), "callback_data": "ref"})
    if has and ext("promo")["enabled"]:
        extra.append({"text": t(L, "🎟 Промокод"), "callback_data": "promo"})
    if extra:
        rows.append(extra)
    last = [{"text": "🌐 " + t(L, "Язык"), "callback_data": "lang"}]
    if ext("support")["enabled"]:
        last.insert(0, {"text": t(L, "💬 Поддержка"), "callback_data": "support"})
    rows.append(last)
    return rows


# ------------------------------------------------------------------ recognising the client

def decode_text(text: str) -> str:
    """Deep links carry the subscription URL-encoded (happ://add/https%3A%2F%2F…): decode a few levels."""
    from urllib.parse import unquote
    out = text
    for _ in range(3):
        nxt = unquote(out)
        if nxt == out:
            break
        out = nxt
    return out


def find_by_key(text: str) -> User | None:
    """Whose subscription link / smart link / share key / bare token is this?"""
    from .db import Device
    from .smartlink import resolve
    text = decode_text(text)
    with SessionLocal() as db:
        candidates = re.findall(r"/(?:sub|c)/([A-Za-z0-9_-]{6,})", text)
        bare = text.strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{7,64}", bare):
            candidates.append(bare)
        for c in candidates:
            u = db.scalar(select(User).where(User.sub_token == c)) or resolve(db, c)
            if u:
                return u
        for uid in re.findall(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", text):
            u = db.scalar(select(User).where(User.uuid == uid.lower()))
            if u:
                return u
            d = db.scalar(select(Device).where(Device.uuid == uid.lower()))
            if d:
                return db.get(User, d.user_id)
    return None


async def bind_and_greet(u: User, chat_id: str):
    from .telegram import bind
    bot = _bot()
    bind(u, chat_id)
    await bot.send(chat_id, t(chat_lang(chat_id), "✅ Узнал вас: <b>{name}</b>. Telegram привязан — буду присылать напоминания об оплате и остатке трафика.",
                              name=html.escape(u.username)), menu(chat_id))
    await bot.send_subscription(u)


async def claim_by_name(chat_id: str, name: str, sender: dict) -> bool:
    """The client wrote only their account name: ask the admins to confirm (anyone could type a name)."""
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == name))
        admins = [a.tg_id for a in db.scalars(select(Admin).where(Admin.tg_id != "", Admin.role.in_(("owner", "operator"))))]
    if not u or u.tg_id == chat_id or not admins:
        return False
    who = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x)
    if sender.get("username"):
        who += f" @{sender['username']}"
    text = (f"🔗 <b>Привязка Telegram</b>\n{html.escape(who or chat_id)} пишет, что он клиент "
            f"<b>{html.escape(u.username)}</b>." + (f"\n⚠️ Сейчас привязан другой Telegram ({u.tg_id})." if u.tg_id else ""))
    for a in admins:
        try:
            await _bot().send(a, text, [[{"text": f"✅ Привязать к {u.username}", "callback_data": f"bind:{u.id}:{chat_id}"},
                                         {"text": "✖️", "callback_data": "noop"}]])
        except Exception:
            pass
    await _bot().send(chat_id, t(chat_lang(chat_id), "Запрос отправлен администратору — как только он подтвердит, я пришлю вашу ссылку. "
                                                     "Быстрее всего — прислать сюда свою ссылку-подписку или ключ из приложения."))
    return True


# ------------------------------------------------------------------ text messages

async def on_text(msg: dict) -> bool:
    """Plain (non-command) text. Returns True when handled."""
    chat_id = str(msg["chat"]["id"])
    text = (msg.get("text") or "").strip()
    sender = msg.get("from", {})
    reply_to = msg.get("reply_to_message")
    admin = _admin(chat_id)
    if admin and reply_to:  # an admin answering a support message in Telegram
        client = support.chat_for_reply(chat_id, reply_to.get("message_id"))
        if client:
            await support.answer(client, text, admin.username)
            await _bot().send(chat_id, "✅ Ответ отправлен клиенту.")
            return True
    u = find_by_key(text)
    if u:
        await bind_and_greet(u, chat_id)
        return True
    if USER_RE.match(text) and await claim_by_name(chat_id, text, sender):
        return True
    if admin:
        return False  # admin chatter: show the admin help
    s = _settings()
    L = chat_lang(chat_id)
    if settings_store.ext(s, "support")["enabled"]:
        ok = await support.incoming(chat_id, text)
        hint = "" if _users(chat_id) else "\n\n" + t(L, "Если у вас уже есть доступ — пришлите сюда ссылку-подписку или ключ из приложения, и я привяжу аккаунт.")
        await _bot().send(chat_id, (t(L, "✉️ Передал ваше сообщение в поддержку — ответ придёт сюда.") if ok else
                                    t(L, "Поддержка сейчас недоступна, попробуйте позже.")) + hint)
        return True
    await _bot().send(chat_id, t(L, "Не нашёл аккаунт по этой ссылке. Пришлите ссылку-подписку целиком "
                                    "(в приложении: профиль → поделиться / копировать) или ключ vless://…"))
    return True


# ------------------------------------------------------------------ purchase

def ensure_account(chat_id: str, sender: dict) -> User:
    """The chat's account, or a new one waiting for its first payment (removed if never paid)."""
    from .api import _new_secrets
    users = _users(chat_id)
    if users:
        return users[0]
    base = re.sub(r"[^A-Za-z0-9_.-]", "", sender.get("username") or "")[:32]
    with SessionLocal() as db:
        name = base if len(base) >= 2 and not db.scalar(select(User).where(User.username == base)) else f"tg{chat_id}".replace("-", "")[:32]
        u = db.scalar(select(User).where(User.username == name))
        if u:
            return u
        who = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x)
        u = User(username=name, tg_id=chat_id, expire_at=utcnow(), note=f"покупка через бота: {who}".strip(),
                 notified={"pending_signup": int(utcnow().timestamp())}, **_new_secrets())
        db.add(u)
        db.flush()
        growth.attach_referrer(db, u, chat_id)
        db.commit()
        return u


async def show_plans(chat_id: str):
    plans = _plans()
    provs = payments.enabled()
    L = chat_lang(chat_id)
    if not plans or not provs:
        await _bot().send(chat_id, t(L, "Онлайн-оплата пока не подключена — напишите в поддержку."))
        return
    users = _users(chat_id)
    lines = [t(L, "💳 <b>Выберите тариф</b>")]
    rows = []
    for p in plans:
        amount, promo = payments.price_for(users[0] if users else None, p)
        price = f"{amount:g} ₽" + (t(L, " (было {old})", old=f"{p.price:g}") if promo else "")
        rows.append([{"text": f"{p.name} · {price}", "callback_data": f"plan:{p.id}"}])
        gb = t(L, "{n} ГБ", n=f"{p.data_limit_gb:g}") if p.data_limit_gb else t(L, "безлимит")
        lines.append(f"• <b>{html.escape(p.name)}</b> — " + t(L, "{days} дн.", days=p.days or "∞") + f", {gb}" +
                     (t(L, ", семья до {n}", n=p.family_size + 1) if p.family_size else ""))
    await _bot().send(chat_id, "\n".join(lines), rows)


async def show_methods(chat_id: str, plan_id: int, sender: dict):
    provs = payments.enabled()
    if len(provs) == 1:
        await pay(chat_id, plan_id, provs[0].name, sender)
        return
    L = chat_lang(chat_id)
    rows = [[{"text": t(L, p.title).replace(" — ", " · "), "callback_data": f"pay:{plan_id}:{p.name}"}] for p in provs]
    await _bot().send(chat_id, t(L, "Способ оплаты:"), rows)


async def pay(chat_id: str, plan_id: int, provider: str, sender: dict):
    u = ensure_account(chat_id, sender)
    L = chat_lang(chat_id)
    try:
        res = await payments.create_order(u.id, plan_id, provider, chat_id, L)
    except RuntimeError as e:
        await _bot().send(chat_id, f"⚠️ {html.escape(t(L, str(e)))}")
        return
    amount = f"{res['amount']:g}"
    if res["text"]:
        await _bot().send(chat_id, t(L, "🧾 <b>Оплата переводом</b>") + f"\n\n{html.escape(res['text'])}",
                          [[{"text": t(L, "✅ Я оплатил"), "callback_data": f"paid:{res['payment_id']}"}]])
    elif res["stars"]:
        await _bot().send(chat_id, t(L, "⭐ К оплате: <b>{stars} звёзд</b> ({amount} ₽).", stars=res["stars"], amount=amount),
                          [[{"text": t(L, "Оплатить {stars} ⭐", stars=res["stars"]), "url": res["url"]}]])
    else:
        await _bot().send(chat_id, t(L, "🧾 Счёт на <b>{amount} ₽</b> создан. После оплаты доступ продлится автоматически, я пришлю подтверждение.",
                                     amount=amount),
                          [[{"text": t(L, "💳 Оплатить {amount} ₽", amount=amount), "url": res["url"]}]])


async def manual_paid(chat_id: str, pid: int):
    with SessionLocal() as db:
        p = db.get(Payment, pid)
        u = db.get(User, p.user_id) if p else None
    L = chat_lang(chat_id)
    if not p or not u or u.tg_id != chat_id or p.status != "pending":
        await _bot().send(chat_id, t(L, "Этот заказ уже обработан."))
        return
    await notify_manual(pid)
    await _bot().send(chat_id, t(L, "Спасибо! Администратор проверит поступление и подтвердит — я сразу напишу."))


async def notify_manual(pid: int):
    """The client says they transferred the money: owners/operators get Confirm / Reject buttons."""
    with SessionLocal() as db:
        p = db.get(Payment, pid)
        u = db.get(User, p.user_id)
        plan = db.get(Plan, p.plan_id) if p.plan_id else None
        admins = [a.tg_id for a in db.scalars(select(Admin).where(Admin.tg_id != "", Admin.role.in_(("owner", "operator"))))]
    for a in admins:
        try:
            await _bot().send(a, f"🧾 <b>Клиент сообщил об оплате переводом</b>\n{html.escape(u.username)} · "
                                 f"{html.escape(plan.name if plan else '')} · <b>{p.amount:g} ₽</b> · заказ №{p.id}",
                              [[{"text": "✅ Подтвердить", "callback_data": f"ok:{p.id}"},
                                {"text": "✖️ Отклонить", "callback_data": f"no:{p.id}"}]])
        except Exception:
            pass


# ------------------------------------------------------------------ callbacks (inline buttons)

async def on_callback(cq: dict):
    bot = _bot()
    data = cq.get("data", "")
    chat_id = str(cq.get("message", {}).get("chat", {}).get("id") or cq.get("from", {}).get("id"))
    sender = cq.get("from", {})
    try:
        await bot.call("answerCallbackQuery", callback_query_id=cq["id"])
    except Exception:
        pass
    admin = _admin(chat_id)
    kind, _, arg = data.partition(":")
    if kind in ("stpl", "sclose"):  # support template / close buttons (mode "bot")
        staff = support.is_staff(chat_id)
        if staff:
            note = await support.staff_callback(staff, data)
            if note:
                await bot.send(chat_id, html.escape(note))
        return
    if kind in ("ok", "no", "bind"):
        if not admin or admin.role not in ("owner", "operator"):
            return
        if kind == "bind":
            uid, _, client = arg.partition(":")
            with SessionLocal() as db:
                u = db.get(User, int(uid))
            if u:
                await bind_and_greet(u, client)
                await bot.send(chat_id, f"✅ Telegram привязан к {html.escape(u.username)}.")
            return
        pid = int(arg)
        if kind == "ok":
            done = await payments.mark_paid(pid, "manual", admin=admin.username)
            await bot.send(chat_id, "✅ Оплата подтверждена, доступ продлён." if done else "Этот заказ уже обработан.")
        else:
            payments.cancel(pid)
            with SessionLocal() as db:
                p = db.get(Payment, pid)
                u = db.get(User, p.user_id) if p else None
            if u and u.tg_id:
                await bot.send(u.tg_id, t(chat_lang(u.tg_id), "❌ Администратор не нашёл ваш перевод. Если это ошибка — напишите в поддержку."))
            await bot.send(chat_id, "Отклонено.")
        return
    if kind == "noop":
        return
    if kind == "lang":
        from .i18n import LANGS, lang_buttons, set_chat_lang
        if arg in LANGS:
            set_chat_lang(chat_id, arg)
            await bot.send(chat_id, t(arg, "✅ Язык: русский"), menu(chat_id))
        else:
            await bot.send(chat_id, "🌐 Язык / Language", lang_buttons())
        return
    await client_action(chat_id, kind, arg, sender)


async def client_action(chat_id: str, kind: str, arg: str, sender: dict):
    from .telegram import start_trial, status_text
    bot = _bot()
    users = _users(chat_id)
    L = chat_lang(chat_id)
    if kind == "sub":
        for u in users:
            await bot.send_subscription(u)
    elif kind == "status":
        await bot.send(chat_id, "\n\n".join(status_text(u, L) for u in users) or t(L, "Аккаунт не найден."), menu(chat_id))
    elif kind == "buy":
        await show_plans(chat_id)
    elif kind == "plan":
        await show_methods(chat_id, int(arg), sender)
    elif kind == "pay":
        plan_id, _, prov = arg.partition(":")
        await pay(chat_id, int(plan_id), prov, sender)
    elif kind == "paid":
        await manual_paid(chat_id, int(arg))
    elif kind == "trial":
        await bot.send(chat_id, await start_trial(chat_id, sender, bool(users)))
        users = _users(chat_id)
        if users:
            await bot.send_subscription(users[0])
    elif kind == "ref":
        await send_ref(chat_id)
    elif kind == "promo":
        await bot.send(chat_id, t(L, "🎟 Отправьте промокод командой: <code>/promo КОД</code>"))
    elif kind == "support":
        await bot.send(chat_id, t(L, "💬 Напишите вопрос одним сообщением — я передам его в поддержку, ответ придёт сюда."))


async def send_ref(chat_id: str):
    s = _settings()
    cfg = settings_store.ext(s, "referral")
    users = _users(chat_id)
    L = chat_lang(chat_id)
    if not cfg["enabled"] or not users:
        await _bot().send(chat_id, t(L, "Реферальная программа сейчас не действует."))
        return
    u = users[0]
    with SessionLocal() as db:
        st = growth.referral_stats(db, db.get(User, u.id))
    paid = sum(1 for x in st["invited"] if x["paid"])
    await _bot().send(chat_id, t(L, "🤝 <b>Пригласите друга</b>\n\nКогда друг оплатит подписку, вы получите <b>+{bonus} дн.</b>, "
                                    "а он — <b>+{friend} дн.</b> в подарок.\n\nВаша ссылка:\n{link}\n\nПриглашено: {invited}, оплатили: {paid}",
                                 bonus=cfg["bonus_days"], friend=cfg["friend_days"], link=st["link"],
                                 invited=len(st["invited"]), paid=paid))


async def promo_command(chat_id: str, code: str):
    users = _users(chat_id)
    L = chat_lang(chat_id)
    if not users:
        await _bot().send(chat_id, t(L, "Сначала привяжите аккаунт — пришлите ссылку-подписку или ключ."))
        return
    if not code:
        await _bot().send(chat_id, t(L, "Укажите код: <code>/promo КОД</code>"))
        return
    try:
        msg = growth.redeem(users[0].id, code, L)
    except ValueError as e:
        msg = f"⚠️ {t(L, str(e))}"
    from .cores.manager import manager
    await manager.sync()
    await _bot().send(chat_id, msg)


# ------------------------------------------------------------------ Telegram Stars

async def on_pre_checkout(q: dict):
    payload = q.get("invoice_payload", "")
    ok = False
    if payload.startswith("pay:") and payload[4:].isdigit():
        with SessionLocal() as db:
            p = db.get(Payment, int(payload[4:]))
            ok = bool(p and p.status == "pending")
    params = {"pre_checkout_query_id": q["id"], "ok": ok}
    if not ok:
        params["error_message"] = t(chat_lang(str(q.get("from", {}).get("id", ""))), "Счёт устарел — создайте новый в боте.")
    await _bot().call("answerPreCheckoutQuery", **params)


async def on_successful_payment(msg: dict):
    sp = msg["successful_payment"]
    payload = sp.get("invoice_payload", "")
    if payload.startswith("pay:") and payload[4:].isdigit():
        await payments.mark_paid(int(payload[4:]), "stars", sp.get("telegram_payment_charge_id", ""))
