"""Plans (tariffs), extensions and the payment history.

Everything that changes a user's paid period goes through apply_plan()/extend(), and every change is
recorded as a Payment. Online payments (providers, webhooks, polling) live in payments.py."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from . import auth
from .db import Payment, Plan, SessionLocal, User, utcnow

GB = 1024 ** 3
router = APIRouter()  # panel API


# ------------------------------------------------------------------ core operations

def extend(u: User, days: int = 0, add_gb: float = 0):
    """Adds days to the paid period (from now if already expired) and/or traffic to the limit."""
    now = utcnow()
    if days:
        base = u.expire_at if u.expire_at and u.expire_at > now else now
        u.expire_at = base + timedelta(days=days)
    if add_gb and u.data_limit:
        u.data_limit += int(add_gb * GB)
    u.notified = {}  # re-arm notifications for the new period / limit


def apply_plan(u: User, plan: Plan):
    """A new paid period of `plan`: extends the expiry, sets the limit and starts traffic from zero."""
    now = utcnow()
    if plan.days:
        base = u.expire_at if u.expire_at and u.expire_at > now else now
        u.expire_at = base + timedelta(days=plan.days)
    else:
        u.expire_at = None
    u.data_limit = int(plan.data_limit_gb * GB)
    u.used_up = u.used_down = 0
    u.multi_device = plan.multi_device
    u.reset_monthly = plan.reset_monthly
    u.last_reset_at = now
    u.plan_id = plan.id
    u.speed_mbps = plan.speed_mbps or 0
    u.enabled = True
    u.notified = {}


def record(db, u: User, plan: Plan | None, amount: float, comment: str, admin: str,
           provider: str = "manual", status: str = "paid", external_id: str = "") -> Payment:
    p = Payment(user_id=u.id, plan_id=plan.id if plan else None, amount=amount,
                currency=plan.currency if plan else "RUB", provider=provider, status=status,
                external_id=external_id, comment=comment[:500], admin=admin,
                paid_at=utcnow() if status == "paid" else None)
    db.add(p)
    return p


def monthly_resets() -> list[str]:
    """Traffic reset every 30 days for users with reset_monthly (called by the stats loop)."""
    now = utcnow()
    done = []
    with SessionLocal() as db:
        for u in db.scalars(select(User).where(User.reset_monthly)):
            start = u.last_reset_at or u.created_at
            if now - start >= timedelta(days=30):
                u.used_up = u.used_down = 0
                u.last_reset_at = now
                u.notified = {k: v for k, v in (u.notified or {}).items() if not k.startswith("t")}
                done.append(u.username)
        db.commit()
    return done


# ------------------------------------------------------------------ panel API

def plan_out(p: Plan) -> dict:
    return {"id": p.id, "name": p.name, "days": p.days, "data_limit_gb": p.data_limit_gb,
            "multi_device": p.multi_device, "reset_monthly": p.reset_monthly, "price": p.price,
            "currency": p.currency, "active": p.active, "sort": p.sort, "family_size": p.family_size,
            "speed_mbps": p.speed_mbps}


class PlanIn(BaseModel):
    name: str
    days: int = 30
    data_limit_gb: float = 0
    multi_device: bool = True
    reset_monthly: bool = False
    price: float = 0
    currency: str = "RUB"
    active: bool = True
    sort: int = 0
    family_size: int = 0
    speed_mbps: int = 0


@router.get("/plans")
def list_plans(_: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        return [plan_out(p) for p in db.scalars(select(Plan).order_by(Plan.sort, Plan.id))]


@router.post("/plans")
def create_plan(body: PlanIn, _: str = Depends(auth.require_admin)):
    if not body.name.strip():
        raise HTTPException(400, "Укажите название тарифа")
    with SessionLocal() as db:
        p = Plan(**{**body.model_dump(), "name": body.name.strip()[:64]})
        db.add(p)
        db.commit()
        return plan_out(p)


@router.patch("/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanIn, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        p = db.get(Plan, plan_id)
        if not p:
            raise HTTPException(404, "Тариф не найден")
        for k, v in body.model_dump().items():
            setattr(p, k, v)
        db.commit()
        return plan_out(p)


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        p = db.get(Plan, plan_id)
        if not p:
            raise HTTPException(404, "Тариф не найден")
        db.delete(p)
        db.commit()
    return {"ok": True}


class ExtendIn(BaseModel):
    plan_id: int | None = None  # a new period of this plan
    days: int = 0  # or quick extension
    add_gb: float = 0
    amount: float | None = None  # money received (defaults to the plan price)
    comment: str = ""


@router.post("/users/{user_id}/extend")
async def extend_user(user_id: int, body: ExtendIn, admin: str = Depends(auth.require_admin)):
    from .cores.manager import manager
    with SessionLocal() as db:
        u = db.get(User, user_id)
        if not u:
            raise HTTPException(404, "Пользователь не найден")
        plan = db.get(Plan, body.plan_id) if body.plan_id else None
        if body.plan_id and not plan:
            raise HTTPException(404, "Тариф не найден")
        if plan:
            apply_plan(u, plan)
            desc = f"тариф «{plan.name}»"
        else:
            if not body.days and not body.add_gb:
                raise HTTPException(400, "Укажите тариф, дни или гигабайты")
            extend(u, body.days, body.add_gb)
            desc = " ".join(x for x in (f"+{body.days} дн." if body.days else "",
                                        f"+{body.add_gb:g} ГБ" if body.add_gb else "") if x)
        amount = body.amount if body.amount is not None else (plan.price if plan else 0)
        record(db, u, plan, amount, " · ".join(x for x in (desc, body.comment) if x), admin)
        db.commit()
    await manager.sync()
    return {"ok": True}


@router.get("/users/{user_id}/payments")
def user_payments(user_id: int, _: str = Depends(auth.require_admin)):
    with SessionLocal() as db:
        plans = {p.id: p.name for p in db.scalars(select(Plan))}
        rows = db.scalars(select(Payment).where(Payment.user_id == user_id).order_by(Payment.id.desc()).limit(100))
        return [{"id": p.id, "plan": plans.get(p.plan_id, ""), "amount": p.amount, "currency": p.currency,
                 "provider": p.provider, "status": p.status, "comment": p.comment, "admin": p.admin,
                 "ts": int((p.paid_at or p.created_at).timestamp())} for p in rows]


@router.get("/payments/summary")
def payments_summary(days: int = 30, _: str = Depends(auth.require_admin)):
    since = utcnow() - timedelta(days=days)
    with SessionLocal() as db:
        rows = list(db.scalars(select(Payment).where(Payment.status == "paid", Payment.paid_at >= since)))
    return {"count": len(rows), "total": round(sum(p.amount for p in rows), 2)}
