import time
from collections import defaultdict

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import JWT_SECRET

TOKEN_TTL = 7 * 24 * 3600
_bearer = HTTPBearer(auto_error=False)
_failures: dict[str, list[float]] = defaultdict(list)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


def make_token(username: str) -> str:
    return jwt.encode({"sub": username, "exp": int(time.time()) + TOKEN_TTL}, JWT_SECRET, "HS256")


def decode_token(token: str) -> str | None:
    try:
        return jwt.decode(token, JWT_SECRET, ["HS256"])["sub"]
    except jwt.PyJWTError:
        return None


def client_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host


def check_rate_limit(ip: str):
    """Max 5 failed logins per 10 minutes per IP."""
    now = time.time()
    _failures[ip] = [t for t in _failures[ip] if now - t < 600]
    if len(_failures[ip]) >= 5:
        raise HTTPException(429, "Слишком много попыток, попробуйте позже")


def register_failure(ip: str):
    _failures[ip].append(time.time())


# Roles: owner > operator > viewer. Checked centrally by method + API section, so endpoints only
# declare Depends(require_admin). Owner-only sections manage the server itself.
OWNER_ONLY = ("/settings", "/firewall", "/ssh", "/nodes", "/telegram-bot", "/admins", "/backups", "/audit",
              "/xray", "/services", "/alerts", "/probe/run", "/probe/settings", "/extensions",
              "/report", "/payments/settings", "/support/settings", "/relays")
ROLE_NAMES = {"owner": "Владелец", "operator": "Оператор", "support": "Поддержка", "viewer": "Наблюдатель"}
# support staff: conversations (answer, templates, status) and a read-only view of clients
SUPPORT_PATHS = ("/support", "/auth/me", "/auth/password", "/auth/2fa")


def _api_path(request: Request) -> str:
    path = request.url.path
    i = path.find("/api/")
    return path[i + 4:] if i >= 0 else path


def allowed(role: str, method: str, path: str) -> bool:
    if role == "owner":
        return True
    if path.startswith(OWNER_ONLY) or (path.startswith("/plans") and method != "GET"):
        return False
    if role == "support":
        return path.startswith(SUPPORT_PATHS) or (method == "GET" and path.startswith(("/users", "/plans")))
    if role == "viewer":
        return method == "GET" or path.startswith(("/auth/password", "/auth/2fa", "/auth/me"))
    return role == "operator"


def require_admin(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    from .db import Admin, SessionLocal  # late import: db imports config only
    from sqlalchemy import select
    name = decode_token(cred.credentials) if cred else None
    if not name:
        raise HTTPException(401, "Не авторизован")
    with SessionLocal() as db:
        admin = db.scalar(select(Admin).where(Admin.username == name))
    if not admin:  # deleted admin: token no longer valid
        raise HTTPException(401, "Не авторизован")
    if not allowed(admin.role, request.method, _api_path(request)):
        raise HTTPException(403, f"Недостаточно прав ({ROLE_NAMES.get(admin.role, admin.role)})")
    request.state.admin = admin.username
    request.state.role = admin.role
    return admin.username
