"""Client-facing localization: the bot, the client page (smart link), the status page and notifications.

Texts are written in Russian with {named} placeholders: t(lang, "Осталось {days} дн.", days=3). Other languages
map the Russian text to a translation in locales/<lang>.json (a missing entry falls back to Russian).
Language: the bot takes it from Telegram (language_code) on the first message and the client can change it
with /lang; the client page takes ?lang=, then a cookie, then the browser's Accept-Language.
Admin-facing messages stay in Russian."""
import json
from functools import lru_cache
from pathlib import Path

LANGS = {"ru": "Русский", "en": "English"}
FLAGS = {"ru": "🇷🇺", "en": "🇬🇧"}
DEFAULT = "ru"
DIR = Path(__file__).parent / "locales"


@lru_cache
def _dict(lang: str) -> dict:
    try:
        return json.loads((DIR / f"{lang}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def t(lang: str | None, text: str, **kw) -> str:
    out = _dict(lang).get(text, text) if lang and lang != DEFAULT else text
    return out.format(**kw) if kw else out


def pick(code: str | None) -> str:
    """Telegram language_code / one Accept-Language tag -> a supported language."""
    c = (code or "").lower().replace("_", "-").split("-")[0]
    if c in LANGS:
        return c
    if c in ("be", "uk", "kk", "uz", "az", "ky", "tg", "hy", "ka", "tk"):  # CIS neighbours usually read Russian
        return "ru"
    return "en" if c else DEFAULT


def from_accept(header: str) -> str:
    for part in (header or "").split(","):
        c = part.split(";")[0].strip().lower().split("-")[0]
        if c in LANGS:
            return c
        if c:
            return pick(c)
    return pick(header.split(",")[0] if header else "")


def chat_lang(chat_id: str | None) -> str:
    """The language chosen for / detected in this Telegram chat."""
    if not chat_id:
        return DEFAULT
    from .db import BotChat, SessionLocal
    with SessionLocal() as db:
        c = db.get(BotChat, str(chat_id))
        return c.lang if c and c.lang in LANGS else DEFAULT


def set_chat_lang(chat_id: str, lang: str):
    from .db import BotChat, SessionLocal
    with SessionLocal() as db:
        c = db.get(BotChat, str(chat_id)) or BotChat(chat_id=str(chat_id))
        c.lang = lang if lang in LANGS else DEFAULT
        db.merge(c)
        db.commit()


def lang_buttons() -> list[list[dict]]:
    items = [{"text": f"{FLAGS[k]} {v}", "callback_data": f"lang:{k}"} for k, v in LANGS.items()]
    return [items[i:i + 2] for i in range(0, len(items), 2)]
