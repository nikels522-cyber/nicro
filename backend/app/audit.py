"""Audit log of admin actions: an ASGI middleware records every successful change (POST/PUT/PATCH/
DELETE) under the panel API with the admin, a readable action, the target and the request body
(secrets stripped). Endpoints need no changes."""
import json
import re

from sqlalchemy import select

from .db import AuditLog, SessionLocal, User

SECRET_KEYS = {"password", "old_password", "new_password", "token", "code", "secret", "private_key"}

# (method, path regex relative to /api) -> action label
ACTIONS = [
    ("POST", r"^/users$", "Создан клиент"),
    ("PATCH", r"^/users/\d+$", "Изменён клиент"),
    ("DELETE", r"^/users/\d+$", "Удалён клиент"),
    ("POST", r"^/users/\d+/reset-traffic$", "Сброшен трафик"),
    ("POST", r"^/users/\d+/regenerate$", "Новые ключи клиента"),
    ("POST", r"^/users/\d+/extend$", "Продление клиента"),
    ("POST", r"^/users/\d+/payments$", "Записана оплата"),
    ("POST", r"^/users/\d+/telegram-test$", "Тест Telegram"),
    ("POST", r"^/users/\d+/send-sub$", "Подписка отправлена в Telegram"),
    ("PATCH", r"^/users/\d+/devices/\d+$", "Изменено устройство"),
    ("DELETE", r"^/users/\d+/devices/\d+$", "Удалено устройство"),
    ("POST", r"^/users/bulk$", "Массовое действие"),
    ("POST", r"^/users/import$", "Импорт клиентов"),
    ("PATCH", r"^/settings$", "Изменены настройки"),
    ("POST", r"^/settings/rotate-reality$", "Сменены ключи Reality"),
    ("PUT", r"^/firewall$", "Изменён файрвол панели"),
    ("PUT", r"^/ssh$", "Изменён SSH"),
    ("POST", r"^/ssh/keys$", "Создан SSH-ключ"),
    ("DELETE", r"^/ssh/keys/", "Удалён SSH-ключ"),
    ("POST", r"^/nodes/join-token$", "Токен подключения сервера"),
    ("PATCH", r"^/nodes/\d+$", "Изменён сервер"),
    ("DELETE", r"^/nodes/\d+$", "Удалён сервер"),
    ("PUT", r"^/telegram-bot$", "Изменён Telegram-бот"),
    ("POST", r"^/plans$", "Создан тариф"),
    ("PATCH", r"^/plans/\d+$", "Изменён тариф"),
    ("DELETE", r"^/plans/\d+$", "Удалён тариф"),
    ("POST", r"^/admins$", "Создан администратор"),
    ("PATCH", r"^/admins/\d+$", "Изменён администратор"),
    ("DELETE", r"^/admins/\d+$", "Удалён администратор"),
    ("POST", r"^/backups$", "Создан бэкап"),
    ("POST", r"^/backups/restore$", "Восстановление из бэкапа"),
    ("POST", r"^/xray/update$", "Обновление Xray"),
    ("PUT", r"^/extensions/", "Изменено дополнение"),
    ("PUT", r"^/backups/storages$", "Изменены облачные хранилища"),
    ("POST", r"^/broadcast$", "Рассылка клиентам"),
    ("PATCH", r"^/auth/me$", "Изменён свой Telegram ID"),
    ("POST", r"^/services/", "Перезапуск сервиса"),
    ("POST", r"^/auth/password$", "Смена пароля"),
    ("POST", r"^/auth/2fa", "Настройка 2FA"),
]


def _label(method: str, path: str) -> str | None:
    for m, rx, label in ACTIONS:
        if m == method and re.search(rx, path):
            return label
    return None


def _clean(body: bytes) -> str:
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return ""

    def strip(x):
        if isinstance(x, dict):
            return {k: ("***" if k in SECRET_KEYS else strip(v)) for k, v in x.items()}
        if isinstance(x, list):
            return [strip(v) for v in x[:20]]
        return x
    return json.dumps(strip(data), ensure_ascii=False)[:1000]


class AuditMiddleware:
    def __init__(self, app, api_prefix: str):
        self.app, self.prefix = app, api_prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH", "DELETE") \
                or not scope["path"].startswith(self.prefix) or scope["path"].endswith("/auth/login"):
            return await self.app(scope, receive, send)
        path = scope["path"][len(self.prefix):]
        label = _label(scope["method"], path)
        if label is None:
            return await self.app(scope, receive, send)
        chunks = []

        async def recv():
            msg = await receive()
            if msg["type"] == "http.request":
                chunks.append(msg.get("body", b""))
            return msg
        target = ""
        m = re.match(r"^/users/(\d+)", path)
        if m:  # resolve before the handler runs (a delete removes the row)
            with SessionLocal() as db:
                u = db.get(User, int(m.group(1)))
                target = u.username if u else f"#{m.group(1)}"
        status = {}

        async def snd(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)
        await self.app(scope, recv, snd)
        if status.get("code", 500) >= 400:
            return
        state = scope.get("state", {})
        headers = dict(scope.get("headers", []))
        ip = headers.get(b"x-forwarded-for", b"").decode().split(",")[0].strip()
        with SessionLocal() as db:
            db.add(AuditLog(admin=state.get("admin", "?"), action=label, target=target or path,
                            details=_clean(b"".join(chunks)), ip=ip))
            db.commit()


def recent(limit: int = 200, offset: int = 0) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).offset(offset).limit(limit))
        return [{"id": r.id, "ts": int(r.ts.timestamp()), "admin": r.admin, "action": r.action,
                 "target": r.target, "details": r.details, "ip": r.ip} for r in rows]
