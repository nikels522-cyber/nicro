"""Online payments. Every provider is ready; to switch one on, fill in its credentials on the
Дополнения → Оплата card (stored in settings["payments"]["providers"][name]).

  yookassa     cards / SBP / wallets (RUB)          shop_id, secret_key
  cryptobot    crypto via @CryptoBot (USDT, TON…)   token from @CryptoBot → Crypto Pay → Create App
  nowpayments  crypto, 200+ coins                   api_key, ipn_secret
  stars        Telegram Stars inside the bot        nothing (rate RUB per star)
  manual       transfer by card/SBP details         text with details; an admin confirms

Flow: create_order() makes a pending Payment and asks the provider for a payment URL (or an
in-bot invoice / instructions). The payment is confirmed by the provider's webhook
(POST /pay/webhook/<name>), by polling the provider (check_loop — works even when webhooks can't
reach the server), by Telegram (Stars) or by an admin (manual). mark_paid() then applies the plan,
counts the promo code, rewards the referrer and notifies the client and the owners."""
import asyncio
import hashlib
import hmac
import json
import logging
import math
from dataclasses import dataclass
from datetime import timedelta

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from . import settings_store
from .db import Payment, Plan, SessionLocal, User, utcnow

log = logging.getLogger("vpnpanel.payments")
public = APIRouter()  # webhooks
PENDING_TTL = timedelta(hours=24)  # a pending payment is canceled after this


@dataclass
class Order:
    payment_id: int
    amount: float  # in RUB (plan currency)
    description: str
    return_url: str
    webhook_url: str
    chat_id: str = ""
    lang: str = "ru"


@dataclass
class Invoice:
    url: str = ""  # where to pay
    external_id: str = ""
    text: str = ""  # instructions instead of a URL (manual)
    stars: int = 0  # Telegram Stars invoice (sent by the bot)


class Provider:
    name = "base"
    title = ""
    hint = ""
    # (key, label, secret?) — the form on the Дополнения page
    fields: list[tuple[str, str, bool]] = []
    webhook = False  # has a webhook URL to paste into the provider's cabinet

    def ready(self, cfg: dict) -> bool:
        return all(cfg.get(k) for k, _, secret in self.fields if secret or k in self.required)

    required: tuple = ()

    async def create(self, cfg: dict, order: Order) -> Invoice:
        raise NotImplementedError

    async def check(self, cfg: dict, p: Payment) -> str | None:
        """Polls the provider: 'paid' | 'canceled' | None (still pending / unknown)."""
        return None

    async def parse_webhook(self, cfg: dict, request: Request) -> tuple[int, str, str] | None:
        """-> (payment id, status 'paid'|'canceled', external id) or None."""
        return None


class YooKassa(Provider):
    name, title = "yookassa", "ЮKassa — карты, СБП, кошельки"
    hint = "Личный кабинет ЮKassa → Интеграция → Ключи API. HTTP-уведомления можно не настраивать: панель сама проверяет оплату."
    fields = [("shop_id", "shopId", False), ("secret_key", "Секретный ключ", True)]
    required = ("shop_id",)
    webhook = True
    API = "https://api.yookassa.ru/v3/payments"

    async def create(self, cfg, order):
        body = {"amount": {"value": f"{order.amount:.2f}", "currency": "RUB"}, "capture": True,
                "confirmation": {"type": "redirect", "return_url": order.return_url},
                "description": order.description[:128], "metadata": {"payment_id": str(order.payment_id)}}
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(self.API, json=body, auth=(cfg["shop_id"], cfg["secret_key"]),
                             headers={"Idempotence-Key": f"nicro-{order.payment_id}"})
        data = r.json()
        if r.status_code >= 400:
            raise RuntimeError(data.get("description") or f"ЮKassa: HTTP {r.status_code}")
        return Invoice(url=data["confirmation"]["confirmation_url"], external_id=data["id"])

    async def _status(self, cfg, ext_id: str) -> dict:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{self.API}/{ext_id}", auth=(cfg["shop_id"], cfg["secret_key"]))
        return r.json()

    async def check(self, cfg, p):
        st = (await self._status(cfg, p.external_id)).get("status")
        return {"succeeded": "paid", "canceled": "canceled"}.get(st)

    async def parse_webhook(self, cfg, request):
        obj = (await request.json()).get("object", {})
        if not obj.get("id"):
            return None
        data = await self._status(cfg, obj["id"])  # notifications aren't signed: ask the API itself
        pid = data.get("metadata", {}).get("payment_id")
        st = {"succeeded": "paid", "canceled": "canceled"}.get(data.get("status"))
        return (int(pid), st, data["id"]) if pid and st else None


class CryptoBot(Provider):
    name, title = "cryptobot", "CryptoBot — USDT, TON, BTC и др."
    hint = ("@CryptoBot → Crypto Pay → Create App → скопируйте API Token. Вебхук необязателен: "
            "панель сама проверяет счета.")
    fields = [("token", "API Token", True), ("assets", "Монеты (через запятую)", False)]
    webhook = True

    def _api(self, cfg) -> str:
        return "https://testnet-pay.crypt.bot/api/" if cfg.get("testnet") else "https://pay.crypt.bot/api/"

    async def _call(self, cfg, method: str, **params):
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(self._api(cfg) + method, json=params, headers={"Crypto-Pay-API-Token": cfg["token"]})
        data = r.json()
        if not data.get("ok"):
            err = data.get("error", {})
            raise RuntimeError(f"CryptoBot: {err.get('name') or err}")
        return data["result"]

    async def create(self, cfg, order):
        params = {"currency_type": "fiat", "fiat": "RUB", "amount": f"{order.amount:.2f}",
                  "accepted_assets": (cfg.get("assets") or "USDT,TON,BTC,ETH,LTC,TRX").replace(" ", ""),
                  "description": order.description[:1024], "payload": str(order.payment_id), "expires_in": 86400}
        if order.return_url.startswith("https://"):
            params.update({"paid_btn_name": "callback", "paid_btn_url": order.return_url})
        inv = await self._call(cfg, "createInvoice", **params)
        return Invoice(url=inv.get("bot_invoice_url") or inv.get("pay_url"), external_id=str(inv["invoice_id"]))

    async def check(self, cfg, p):
        res = await self._call(cfg, "getInvoices", invoice_ids=p.external_id)
        items = res.get("items", []) if isinstance(res, dict) else res
        st = items[0].get("status") if items else None
        return {"paid": "paid", "expired": "canceled"}.get(st)

    async def parse_webhook(self, cfg, request):
        raw = await request.body()
        secret = hashlib.sha256(cfg["token"].encode()).digest()
        sig = hmac.new(secret, raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, request.headers.get("crypto-pay-api-signature", "")):
            return None
        data = json.loads(raw)
        inv = data.get("payload", {})
        if data.get("update_type") != "invoice_paid" or not str(inv.get("payload", "")).isdigit():
            return None
        return int(inv["payload"]), "paid", str(inv.get("invoice_id", ""))


class NowPayments(Provider):
    name, title = "nowpayments", "NOWPayments — 200+ криптовалют"
    hint = ("nowpayments.io → Settings → Payments: API key и IPN secret. Укажите IPN callback URL (ниже). "
            "Если RUB не принимается, поставьте валюту usd и курс рубля.")
    fields = [("api_key", "API key", True), ("ipn_secret", "IPN secret", True),
              ("currency", "Валюта цены (rub / usd)", False), ("rate", "Курс: рублей за 1 ед. валюты", False)]
    webhook = True

    async def create(self, cfg, order):
        cur = (cfg.get("currency") or "rub").lower()
        rate = float(cfg.get("rate") or 1) if cur != "rub" else 1
        body = {"price_amount": round(order.amount / rate, 2), "price_currency": cur,
                "order_id": str(order.payment_id), "order_description": order.description[:200],
                "ipn_callback_url": order.webhook_url}
        if order.return_url.startswith("http"):
            body.update({"success_url": order.return_url, "cancel_url": order.return_url})
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.nowpayments.io/v1/invoice", json=body, headers={"x-api-key": cfg["api_key"]})
        data = r.json()
        if r.status_code >= 400 or "invoice_url" not in data:
            raise RuntimeError(f"NOWPayments: {data.get('message') or r.status_code}")
        return Invoice(url=data["invoice_url"], external_id=str(data["id"]))

    async def parse_webhook(self, cfg, request):
        raw = await request.body()
        data = json.loads(raw)
        body = json.dumps(data, sort_keys=True, separators=(",", ":"))
        sig = hmac.new(cfg["ipn_secret"].encode(), body.encode(), hashlib.sha512).hexdigest()
        if not hmac.compare_digest(sig, request.headers.get("x-nowpayments-sig", "")):
            return None
        st = {"finished": "paid", "failed": "canceled", "expired": "canceled"}.get(data.get("payment_status"))
        oid = str(data.get("order_id", ""))
        return (int(oid), st, str(data.get("invoice_id") or data.get("payment_id"))) if st and oid.isdigit() else None


class Stars(Provider):
    name, title = "stars", "Telegram Stars — оплата звёздами в боте"
    hint = "Ничего подключать не нужно: оплата идёт внутри бота. Укажите курс — сколько рублей стоит одна звезда."
    fields = [("rub_per_star", "Рублей за 1 ⭐", False)]
    required = ()

    def ready(self, cfg):
        from .telegram import bot
        return bool(bot.token())

    async def create(self, cfg, order):
        stars = max(1, math.ceil(order.amount / float(cfg.get("rub_per_star") or 1.8)))
        from .telegram import bot
        link = await bot.call("createInvoiceLink", title="nicro VPN", description=order.description[:255],
                              payload=f"pay:{order.payment_id}", currency="XTR",
                              prices=[{"label": order.description[:32], "amount": stars}])
        return Invoice(url=link, stars=stars)


class Manual(Provider):
    name, title = "manual", "Перевод по реквизитам (подтверждает администратор)"
    hint = "Клиент видит реквизиты и нажимает «Я оплатил» — вам в Telegram придёт кнопка «Подтвердить»."
    fields = [("text", "Реквизиты и инструкция для клиента", False)]
    required = ("text",)

    async def create(self, cfg, order):
        from .i18n import t
        return Invoice(text=f"{cfg['text']}\n\n" + t(order.lang, "Сумма: {amount} ₽ · заказ №{id}",
                                                       amount=f"{order.amount:.0f}", id=order.payment_id))


PROVIDERS: dict[str, Provider] = {p.name: p for p in (YooKassa(), CryptoBot(), NowPayments(), Stars(), Manual())}


# ------------------------------------------------------------------ settings

def _all_cfg() -> tuple[dict, dict]:
    with SessionLocal() as db:
        s = settings_store.load(db)
    return s, s.get("payments", {}).get("providers", {})


def enabled() -> list[Provider]:
    _, cfg = _all_cfg()
    return [p for n, p in PROVIDERS.items() if cfg.get(n, {}).get("enabled") and p.ready(cfg.get(n, {}))]


def webhook_url(s: dict, name: str) -> str:
    return f"{s['sub_base_url'].rstrip('/')}/pay/webhook/{name}"


def public_settings() -> dict:
    s, cfg = _all_cfg()
    out = []
    for n, p in PROVIDERS.items():
        c = cfg.get(n, {})
        out.append({"name": n, "title": p.title, "hint": p.hint, "enabled": bool(c.get("enabled")),
                    "ready": p.ready(c), "webhook": webhook_url(s, n) if p.webhook else "",
                    "fields": [{"key": k, "label": label, "secret": sec,
                                "value": ("***" if c.get(k) else "") if sec else c.get(k, "")}
                               for k, label, sec in p.fields]})
    return {"providers": out, "return_url": s.get("payments", {}).get("return_url", "")}


def save_settings(items: dict, return_url: str | None = None):
    with SessionLocal() as db:
        s = settings_store.load(db)
        pay = s.setdefault("payments", {"providers": {}, "return_url": ""})
        provs = pay.setdefault("providers", {})
        for n, values in items.items():
            p = PROVIDERS.get(n)
            if not p:
                continue
            cur = dict(provs.get(n, {}))
            for k, _, sec in p.fields:
                if k in values and not (sec and values[k] == "***"):
                    cur[k] = str(values[k]).strip()
            if "enabled" in values:
                cur["enabled"] = bool(values["enabled"])
            provs[n] = cur
        if return_url is not None:
            pay["return_url"] = return_url.strip()
        settings_store.save(db, s)


# ------------------------------------------------------------------ orders

def price_for(u: User | None, plan: Plan) -> tuple[float, int | None]:
    """Plan price with the user's pending promo discount -> (amount, promo id)."""
    from . import growth
    promo = growth.pending_discount(u) if u else None
    if promo:
        return round(plan.price * (1 - promo.value / 100), 2), promo.id
    return plan.price, None


async def create_order(user_id: int, plan_id: int, provider: str, chat_id: str = "", lang: str = "ru") -> dict:
    s, cfg = _all_cfg()
    p = PROVIDERS.get(provider)
    pcfg = cfg.get(provider, {})
    if not p or not pcfg.get("enabled") or not p.ready(pcfg):
        raise RuntimeError("Этот способ оплаты не подключён")
    from .smartlink import url as smart_url
    with SessionLocal() as db:
        u, plan = db.get(User, user_id), db.get(Plan, plan_id)
        if not u or not plan or not plan.active or plan.price <= 0:
            raise RuntimeError("Тариф недоступен для оплаты")
        recent = db.scalar(select(func.count()).select_from(Payment).where(
            Payment.user_id == u.id, Payment.status == "pending", Payment.created_at > utcnow() - timedelta(hours=1)))
        if recent >= 5:
            raise RuntimeError("Слишком много неоплаченных счетов — оплатите созданный или подождите час")
        amount, promo_id = price_for(u, plan)
        pay = Payment(user_id=u.id, plan_id=plan.id, amount=amount, currency=plan.currency, provider=provider,
                      status="pending", comment=f"онлайн-оплата: тариф «{plan.name}»", admin="",
                      meta={"promo_id": promo_id, "chat_id": chat_id, "base_price": plan.price})
        db.add(pay)
        db.commit()
        ret = s.get("payments", {}).get("return_url") or f"{smart_url(u, s)}?page=1&paid={pay.id}"
        order = Order(pay.id, amount, f"nicro VPN · {plan.name} · {u.username}", ret, webhook_url(s, provider), chat_id, lang)
        pid = pay.id
    try:
        inv = await p.create(pcfg, order)
    except Exception as e:
        with SessionLocal() as db:
            db.get(Payment, pid).status = "failed"
            db.commit()
        log.warning("%s invoice failed: %s", provider, e)
        raise RuntimeError(f"Не удалось создать счёт: {e}")
    with SessionLocal() as db:
        pay = db.get(Payment, pid)
        pay.external_id = inv.external_id or f"{provider}-{pid}"
        db.commit()
    return {"payment_id": pid, "amount": amount, "url": inv.url, "text": inv.text, "stars": inv.stars,
            "provider": provider}


async def mark_paid(payment_id: int, provider: str | None = None, external_id: str = "", admin: str = "") -> bool:
    """Applies a confirmed payment exactly once. Returns False when it was already applied / unknown."""
    from . import billing, growth
    from .cores.manager import manager
    from .telegram import bot, status_text
    with SessionLocal() as db:
        p = db.get(Payment, payment_id)
        if not p or p.status == "paid" or (provider and p.provider != provider):
            return False
        u = db.get(User, p.user_id)
        plan = db.get(Plan, p.plan_id) if p.plan_id else None
        if plan:
            billing.apply_plan(u, plan)
        p.status, p.paid_at = "paid", utcnow()
        if external_id:
            p.external_id = external_id
        if admin:
            p.admin = admin
        promo_id = (p.meta or {}).get("promo_id")
        if promo_id:
            growth.consume_promo(db, promo_id, u)
        u.notified = {k: v for k, v in (u.notified or {}).items() if k != "pending_signup"}
        rewards = growth.referral_reward(db, u, p)
        db.commit()
        amount, username, tg, text = p.amount, u.username, u.tg_id, status_text(u)
        plan_name = plan.name if plan else ""
    await manager.sync()
    if tg:
        from .i18n import chat_lang, t
        L = chat_lang(tg)
        try:
            with SessionLocal() as db:
                text = status_text(db.get(User, p.user_id), L)
            await bot.send(tg, t(L, "✅ <b>Оплата получена, спасибо!</b>") + "\n\n" + text)
            with SessionLocal() as db:
                await bot.send_subscription(db.get(User, p.user_id))
        except Exception as e:
            log.warning("paid notify failed: %s", e)
    for chat, msg in rewards:
        try:
            await bot.send(chat, msg)
        except Exception:
            pass
    await bot.send_admins(f"💰 <b>nicro:</b> оплата {amount:.0f} ₽ · {username} · {plan_name} ({p.provider})",
                          roles=("owner", "operator"))
    return True


def cancel(payment_id: int):
    with SessionLocal() as db:
        p = db.get(Payment, payment_id)
        if p and p.status == "pending":
            p.status = "canceled"
            db.commit()


@public.post("/pay/webhook/{provider}")
async def webhook(provider: str, request: Request):
    p = PROVIDERS.get(provider)
    _, cfg = _all_cfg()
    if not p or not cfg.get(provider, {}).get("enabled"):
        raise HTTPException(404)
    try:
        ev = await p.parse_webhook(cfg[provider], request)
    except Exception as e:
        log.warning("%s webhook: %s", provider, e)
        raise HTTPException(400)
    if ev:
        pid, status, ext = ev
        if status == "paid":
            await mark_paid(pid, provider, ext)
        elif status == "canceled":
            cancel(pid)
    return {"ok": True}


def cleanup_signups():
    """Accounts created in the bot for a purchase that was never paid disappear after 3 days."""
    limit = utcnow() - timedelta(days=3)
    with SessionLocal() as db:
        for u in db.scalars(select(User)):
            ts = (u.notified or {}).get("pending_signup")
            if ts and u.created_at < limit and not db.scalar(
                    select(Payment).where(Payment.user_id == u.id, Payment.status == "paid")):
                db.delete(u)
        db.commit()


async def check_loop():
    """Confirms pending payments by asking the providers (no public webhook needed)."""
    n = 0
    while True:
        await asyncio.sleep(20)
        n += 1
        if n % 180 == 0:
            try:
                cleanup_signups()
            except Exception:
                log.exception("signup cleanup failed")
        try:
            _, cfg = _all_cfg()
            now = utcnow()
            with SessionLocal() as db:
                pending = list(db.scalars(select(Payment).where(Payment.status == "pending")))
                for p in pending:
                    if now - p.created_at > PENDING_TTL:
                        p.status = "canceled"
                db.commit()
            for p in pending:
                prov = PROVIDERS.get(p.provider)
                if not prov or now - p.created_at > PENDING_TTL or not cfg.get(p.provider, {}).get("enabled"):
                    continue
                # fresh orders every 20 s, older ones every few minutes
                if now - p.created_at > timedelta(hours=1) and now.minute % 5:
                    continue
                try:
                    st = await prov.check(cfg[p.provider], p)
                except Exception as e:
                    log.debug("check %s #%s: %s", p.provider, p.id, e)
                    continue
                if st == "paid":
                    await mark_paid(p.id, p.provider)
                elif st == "canceled":
                    cancel(p.id)
        except Exception:
            log.exception("payment check failed")

