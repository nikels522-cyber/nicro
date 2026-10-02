"""Smart link: one short URL per client, /c/<code>. Opened in a browser it shows a page adapted to the
device (recommended app for Android / iPhone / Windows / Mac / Linux, one-tap import, QR for another
device, Telegram binding); fetched by a VPN app it simply works as the subscription."""
import hashlib
import hmac

from sqlalchemy.orm import Session

from . import config
from .db import User

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _b36(n: int) -> str:
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = ALPHABET[r] + out
        if not n:
            return out


def _sig(u: User) -> str:
    return hmac.new(config.JWT_SECRET.encode(), f"c:{u.id}:{u.sub_token}".encode(), hashlib.sha256).hexdigest()[:6]


def code(u: User) -> str:
    return _b36(u.id) + _sig(u)  # regenerating the user's keys changes sub_token -> old smart link dies


def resolve(db: Session, c: str) -> User | None:
    if len(c) < 7 or not c.isalnum():
        return None
    try:
        u = db.get(User, int(c[:-6], 36))
    except ValueError:
        return None
    return u if u and hmac.compare_digest(_sig(u), c[-6:]) else None


def url(u: User, s: dict) -> str:
    return f"{s['sub_base_url'].rstrip('/')}/c/{code(u)}"


def device_of(user_agent: str) -> str:
    ua = user_agent.lower()
    if "iphone" in ua or "ipad" in ua or "ios" in ua:
        return "ios"
    if "android" in ua:
        return "android"
    if "windows" in ua:
        return "windows"
    if "mac os" in ua or "macintosh" in ua:
        return "mac"
    if "linux" in ua:
        return "linux"
    return "other"
