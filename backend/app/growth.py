"""Growth: promo codes and the referral program.

Promo codes: `percent` gives a discount on the client's next online payment (remembered on the user
until they pay), `days` adds free days right away. Each code works once per client and may have a
use limit and an end date.

Referral: every client has a personal bot link t.me/<bot>?start=ref_<code>. A newcomer who arrives
through it is remembered (BotChat.ref_user_id) and linked when their account is created (trial or
purchase). On the friend's first paid payment the inviter gets `bonus_days` and the friend
`friend_days` (Дополнения → Реферальная программа)."""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from . import auth, billing, settings_store
from .db import BotChat, Payment, PromoCode, PromoUse, SessionLocal, User, utcnow
from .i18n import chat_lang, t

router = APIRouter()
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


def _ext(name: str) -> dict:
    with SessionLocal() as db:
        return settings_store.ext(settings_store.load(db), name)


# ------------------------------------------------------------------ promo codes

def _valid(db, code: str, u: User | None) -> PromoCode:
    p = db.scalar(select(PromoCode).where(func.upper(PromoCode.code) == code.strip().upper()))
    if not p or not p.active:
        raise ValueError("Промокод не найден")
    if p.expires_at and p.expires_at < utcnow():
        raise ValueError("Срок действия промокода истёк")
    if p.max_uses and p.used >= p.max_uses:
        raise ValueError("Промокод больше не действует")
    if u and db.scalar(select(PromoUse).where(PromoUse.promo_id == p.id, PromoUse.user_id == u.id)):
        raise ValueError("Вы уже использовали этот промокод")
    return p


def redeem(user_id: int, code: str, lang: str = "ru") -> str:
    """Client enters a code (bot / client page). Returns a message for the client; raises ValueError."""
    if not _ext("promo")["enabled"]:
        raise ValueError("Промокоды сейчас не принимаются")
    with SessionLocal() as db:
        u = db.get(User, user_id)
        p = _valid(db, code, u)
        if p.kind == "days":
            billing.extend(u, int(p.value))
            consume_promo(db, p.id, u)
            billing.record(db, u, None, 0, f"промокод {p.code}: +{int(p.value)} дн.", "промокод")
            db.commit()
            return t(lang, "🎟 Промокод принят: +{days} дн. к подписке.", days=int(p.value))
        u.promo_id = p.id
        db.commit()
        return t(lang, "🎟 Промокод принят: скидка {pct}% на следующую оплату.", pct=f"{p.value:g}")


def pending_discount(u: User) -> PromoCode | None:
    if not u or not u.promo_id:
        return None
    with SessionLocal() as db:
        p = db.get(PromoCode, u.promo_id)
        if not p:
            return None
        try:
            _valid(db, p.code, u)
        except ValueError:
            return None
    return p if p.kind == "percent" else None


def consume_promo(db, promo_id: int, u: User):
    p = db.get(PromoCode, promo_id)
    if not p or db.scalar(select(PromoUse).where(PromoUse.promo_id == p.id, PromoUse.user_id == u.id)):
        return
    p.used += 1
    db.add(PromoUse(promo_id=p.id, user_id=u.id))
    if u.promo_id == promo_id:
        u.promo_id = None


# ------------------------------------------------------------------ referral

def ref_link(u: User) -> str | None:
    from .smartlink import code
    from .telegram import bot
    return f"https://t.me/{bot.username}?start=ref_{code(u)}" if bot.username else None


def remember_arrival(chat_id: str, ref_code: str) -> User | None:
    """A newcomer opened someone's referral link: remember who invited them."""
    from .smartlink import resolve
    with SessionLocal() as db:
        inviter = resolve(db, ref_code)
        if not inviter or inviter.tg_id == chat_id:
            return None
        chat = db.get(BotChat, chat_id) or BotChat(chat_id=chat_id)
        if chat.ref_user_id is None:
            chat.ref_user_id = inviter.id
        db.merge(chat)
        db.commit()
        return inviter


def attach_referrer(db, u: User, chat_id: str):
    """Called when an account is created for a Telegram chat."""
    chat = db.get(BotChat, chat_id)
    if chat and chat.ref_user_id and chat.ref_user_id != u.id and not u.referred_by:
        u.referred_by = chat.ref_user_id


def referral_reward(db, u: User, p: Payment) -> list[tuple[str, str]]:
    """First real payment of an invited client: bonus days for both. Returns messages to send."""
    cfg = _ext("referral")
    if not cfg["enabled"] or not u.referred_by or u.ref_rewarded or p.amount <= 0:
        return []
    inviter = db.get(User, u.referred_by)
    u.ref_rewarded = True
    out = []
    if int(cfg.get("friend_days") or 0):
        billing.extend(u, int(cfg["friend_days"]))
        billing.record(db, u, None, 0, f"бонус за приглашение: +{cfg['friend_days']} дн.", "рефералы")
    if inviter and int(cfg.get("bonus_days") or 0):
        billing.extend(inviter, int(cfg["bonus_days"]))
        billing.record(db, inviter, None, 0, f"друг {u.username} оплатил: +{cfg['bonus_days']} дн.", "рефералы")
        if inviter.tg_id:
            out.append((inviter.tg_id, t(chat_lang(inviter.tg_id), "🎁 Ваш друг оплатил подписку — вам +{days} дн. Спасибо!",
                                         days=cfg["bonus_days"])))
    return out


def referral_stats(db, u: User) -> dict:
    invited = list(db.scalars(select(User).where(User.referred_by == u.id)))
    inviter = db.get(User, u.referred_by) if u.referred_by else None
    return {"invited": [{"id": x.id, "username": x.username, "paid": x.ref_rewarded} for x in invited],
            "invited_by": {"id": inviter.id, "username": inviter.username} if inviter else None,
            "link": ref_link(u)}


# ------------------------------------------------------------------ panel API

def promo_out(p: PromoCode) -> dict:
    return {"id": p.id, "code": p.code, "kind": p.kind, "value": p.value, "max_uses": p.max_uses, "used": p.used,
            "expires_at": int(p.expires_at.timestamp()) if p.expires_at else None, "active": p.active, "note": p.note}


class PromoIn(BaseModel):
    code: str
    kind: str = "percent"
    value: float = 10
    max_uses: int = 0
    expires_at: int | None = None  # unix time
    active: bool = True
    note: str = ""


def _check(body: PromoIn):
    if not CODE_RE.match(body.code):
        raise HTTPException(400, "Код: 3–32 символа, латиница, цифры, _ -")
    if body.kind not in ("percent", "days"):
        raise HTTPException(400, "Тип: скидка % или дни")
    if body.kind == "percent" and not 0 < body.value <= 100:
        raise HTTPException(400, "Скидка — от 1 до 100%")
    if body.kind == "days" and not 1 <= body.value <= 3650:
        raise HTTPException(400, "Дней — от 1 до 3650")


def _apply(p: PromoCode, body: PromoIn):
    p.code, p.kind, p.value, p.max_uses = body.code.upper(), body.kind, body.value, max(body.max_uses, 0)
    p.expires_at = datetime.utcfromtimestamp(body.expires_at) if body.expires_at else None
    p.active, p.note = body.active, body.note[:200]


@router.get("/promos")
def list_promos(_: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        return [promo_out(p) for p in db.scalars(select(PromoCode).order_by(PromoCode.id.desc()))]


@router.post("/promos")
def create_promo(body: PromoIn, _: str = Depends(auth.require_admin)):
    _check(body)
    with SessionLocal() as db:
        if db.scalar(select(PromoCode).where(func.upper(PromoCode.code) == body.code.upper())):
            raise HTTPException(400, "Такой код уже есть")
        p = PromoCode()
        _apply(p, body)
        db.add(p)
        db.commit()
        return promo_out(p)


@router.patch("/promos/{pid}")
def update_promo(pid: int, body: PromoIn, _: str = Depends(auth.require_admin)):
    _check(body)
    with SessionLocal() as db:
        p = db.get(PromoCode, pid)
        if not p:
            raise HTTPException(404, "Промокод не найден")
        _apply(p, body)
        db.commit()
        return promo_out(p)


@router.delete("/promos/{pid}")
def delete_promo(pid: int, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        p = db.get(PromoCode, pid)
        if p:
            db.delete(p)
            db.commit()
    return {"ok": True}
