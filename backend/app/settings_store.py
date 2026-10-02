"""Server-wide protocol settings stored in the DB (single JSON row)."""
import base64
import hashlib
import secrets
import uuid as uuidlib

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy.orm import Session

from . import config
from .db import Setting

KEY = "server"


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def gen_reality_keys() -> tuple[str, str]:
    priv = X25519PrivateKey.generate()
    raw_priv = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                  serialization.NoEncryption())
    raw_pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64url(raw_priv), _b64url(raw_pub)


def reality_public_from_private(private: str) -> str:
    raw = base64.urlsafe_b64decode(private + "=" * (-len(private) % 4))
    pub = X25519PrivateKey.from_private_bytes(raw).public_key()
    return _b64url(pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def gen_ss_key() -> str:
    return base64.b64encode(secrets.token_bytes(16)).decode()


def defaults() -> dict:
    priv, pub = gen_reality_keys()
    return {
        "host": config.PUBLIC_HOST,
        "sub_base_url": config.SUB_BASE_URL,
        "reality_private": priv,
        "reality_public": pub,
        "short_id": secrets.token_hex(8),
        # www.microsoft.com breaks REALITY (oversized Akamai cert chain); apple works reliably
        "reality_sni": "www.apple.com",
        "fingerprint": "chrome",
        "xhttp_path": "/" + secrets.token_hex(6),
        "ss_method": "2022-blake3-aes-128-gcm",
        "ss_server_key": gen_ss_key(),
        "hy_obfs": True,
        "hy_obfs_password": secrets.token_urlsafe(18),
        "hy_masquerade": "https://www.apple.com",
        "hy_stats_secret": secrets.token_hex(16),
        "ports": {"vless": 443, "xhttp": 8443, "ss": 8388, "hy": 443, "steal": 2083, "steal_xhttp": 2087},
        "protocols": {"vless": True, "xhttp": True, "ss": True, "hy": True, "steal": True},
        # "self-steal" REALITY: the SNI is our own domain pointing at the entry IP, and the camouflage
        # site with a real certificate is served locally by Caddy. DPI that flags SNI/IP mismatch
        # (e.g. apple.com on a non-Apple IP) sees an ordinary site. Empty = disabled.
        "steal_domain": "",
        # cascade entry points: [{"name": "RU", "host": "1.2.3.4", "domain": "ru.example.com"}]
        "relays": [],
        "relay_token": secrets.token_urlsafe(24),  # auth for relay metrics agents
        "tg_bot_token": "",  # Telegram bot for client notifications (telegram.py)
        # panel access allowlist (firewall.py): {"enabled", "allow": [{"cidr", "note"}], "via_vpn"}
        "panel_fw": {"enabled": False, "allow": [], "via_vpn": True},
        # hidden identity used by the blocking monitor (probe.py); present on every server
        "probe_uuid": str(uuidlib.uuid4()),
        "probe_ss_key": gen_ss_key(),
        "panel_domain": "",  # own domain for the panel + subscriptions (Caddy, cores/caddy.py)
        # how the main server is called in the panel and in client apps; detected by IP on first start
        "main_name": "", "main_country": "",
        "hide_ip_new": True,  # new clients get keys with domains instead of IPs (users.hide_ip)
        "regru": {"username": "", "password": ""},  # optional: auto-update relay DNS on IP change
        "xray_update_seq": 0,  # bumped by "update Xray": cluster nodes update on change
        "storages": [],  # cloud storages for backups (storage.py)
        # extensions (Дополнения): switchable features and their settings
        "ext": {k: dict(v) for k, v in EXT_DEFAULTS.items()},
        # online payments (payments.py): per-provider credentials, filled in on the Дополнения page
        "payments": {"providers": {}, "return_url": ""},
    }


# every extension with its default options; ext(s, name) merges these with what is stored
EXT_DEFAULTS = {
    "mtproto": {"enabled": True},
    "adblock": {"enabled": False},
    "smartlink": {"enabled": True},
    "trial": {"enabled": False, "plan_id": None, "days": 1, "gb": 2},
    # referral program: the inviter gets `bonus_days` when the friend pays for the first time,
    # the friend gets `friend_days` on top of the paid period
    "referral": {"enabled": False, "bonus_days": 7, "friend_days": 3},
    "promo": {"enabled": True},
    # support (support.py): where client messages go — "panel" only, "bot" (the main bot messages the staff)
    # or "staffbot" (a separate bot for the staff); which roles get them; quick-reply templates
    "support": {"enabled": True, "mode": "bot", "staff_bot_token": "", "roles": ["owner", "operator", "support"],
                "autoreply": "", "templates": [
                    {"id": "t1", "title": "Приветствие", "text": "Здравствуйте, {name}! Сейчас посмотрю и отвечу."},
                    {"id": "t2", "title": "Обновить подписку",
                     "text": "Обновите, пожалуйста, подписку в приложении (потяните список серверов вниз или кнопка ⟳) и выберите сервер с 🛡."},
                    {"id": "t3", "title": "Мобильный интернет",
                     "text": "На мобильном интернете выберите сервер с пометкой «мобильный» и выключите «Частный DNS» в настройках телефона."},
                    {"id": "t4", "title": "Ссылка на подключение", "text": "Ваша ссылка для подключения: {link}"},
                    {"id": "t5", "title": "Срок подписки", "text": "Ваша подписка действует до {expire} (осталось {days} дн.). Продлить: /buy"},
                    {"id": "t6", "title": "Готово", "text": "Готово! Если что-то ещё — пишите."},
                ]},
    "family": {"enabled": True},
    # Happ: sites of Russia go direct, everything else through the VPN (routing profile in the subscription)
    "routing": {"enabled": False, "extra_direct": []},
    # Cloudflare WARP as the exit for services that block datacenter IPs (ChatGPT, Gemini, ...)
    "warp": {"enabled": False, "domains": [], "account": {}},
    "status": {"enabled": False, "title": "nicro — состояние серверов"},
    "failover": {"enabled": True},  # hide keys of servers that are down from subscriptions
    "report": {"enabled": False, "weekday": 0, "hour": 10, "last": ""},  # weekly report to owners
    "speed": {"enabled": False},  # per-user speed limits (speed.py)
}


def ext(s: dict, name: str) -> dict:
    """Options of an extension (stored values over defaults)."""
    return {**EXT_DEFAULTS.get(name, {}), **s.get("ext", {}).get(name, {})}


_DEFAULT_KEYS = set(defaults())
_NESTED = ("ports", "protocols")
_NESTED_DEFAULTS = {k: defaults()[k] for k in _NESTED}


def load(db: Session) -> dict:
    row = db.get(Setting, KEY)
    if row is None:
        row = Setting(key=KEY, value=defaults())
        db.add(row)
        db.commit()
    v = row.value
    stale = _DEFAULT_KEYS - set(v) or any(set(_NESTED_DEFAULTS[k]) - set(v.get(k, {})) for k in _NESTED)
    if stale:  # new fields added in an update
        d = defaults()
        row.value = {**d, **v, **{k: {**d[k], **v.get(k, {})} for k in _NESTED}}
        db.commit()
    return dict(row.value)


def steal_names(s: dict) -> list[str]:
    """All own domains used as REALITY SNI (direct + relays)."""
    names = [s.get("steal_domain", "")] + [r.get("domain", "") for r in s.get("relays", [])]
    return sorted({n for n in names if n})


def save(db: Session, value: dict) -> dict:
    row = db.get(Setting, KEY)
    row.value = value
    db.commit()
    return value


def hy_cert_pin() -> str | None:
    """SHA-256 fingerprint of the Hysteria2 self-signed certificate (for pinSHA256)."""
    try:
        cert = x509.load_pem_x509_certificate(config.HY_CERT.read_bytes())
    except (OSError, ValueError):
        return None
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


# affect client links / monitoring, not the cores
LINK_ONLY_FIELDS = {"host", "sub_base_url", "fingerprint", "relays", "relay_token", "tg_bot_token", "panel_fw",
                    "probe_uuid", "probe_ss_key", "panel_domain", "regru", "xray_update_seq", "backup",
                    "alerts", "probe", "storages", "ext", "payments", "main_name", "main_country", "hide_ip_new"}


def core_view(s: dict) -> dict:
    """Settings the running cores depend on; changing anything else must not restart them."""
    view = {k: v for k, v in s.items() if k not in LINK_ONLY_FIELDS}
    view["steal_names"] = steal_names(s)  # relays' domains matter to REALITY serverNames
    view["relay_proxy"] = any(r.get("host") for r in s.get("relays", []))  # PROXY-protocol twin inbounds
    view["adblock"] = bool(s.get("ext", {}).get("adblock", {}).get("enabled"))  # ads/trackers blocked in Xray
    warp = ext(s, "warp")
    view["warp"] = ({"account": warp["account"], "domains": warp_domains(warp)}
                    if warp["enabled"] and warp.get("account") else None)
    return view


# services that refuse datacenter IPs: through WARP when that extension is on
WARP_DEFAULT_DOMAINS = ["openai.com", "chatgpt.com", "oaistatic.com", "oaiusercontent.com", "sora.com",
                        "gemini.google.com", "aistudio.google.com", "generativelanguage.googleapis.com",
                        "bard.google.com", "notebooklm.google.com", "claude.ai", "anthropic.com",
                        "grok.com", "x.ai", "perplexity.ai", "copilot.microsoft.com", "netflix.com"]


def warp_domains(cfg: dict) -> list[str]:
    extra = [d.strip().lower() for d in cfg.get("domains", []) if d.strip()]
    return sorted(set(WARP_DEFAULT_DOMAINS + extra))


def flag(country: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country.upper()) if len(country or "") == 2 else "🌐"


def main_label(s: dict) -> str:
    """E.g. "🇳🇱 Амстердам" — the main server as shown in the panel, status page and key names."""
    return f"{flag(s.get('main_country', ''))} {s.get('main_name') or 'Основной сервер'}"


async def detect_main(s: dict) -> dict:
    """Fills main_country / main_name from the server's IP once (ipinfo.io); failures are silent."""
    if s.get("main_country"):
        return s
    import httpx
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            info = (await c.get(f"https://ipinfo.io/{s['host']}/json")).json()
    except Exception:
        return s
    if len(info.get("country", "")) == 2:
        s["main_country"] = info["country"]
        s["main_name"] = s.get("main_name") or info.get("city", "")
    return s


PUBLIC_FIELDS = ["host", "sub_base_url", "reality_public", "short_id", "reality_sni", "fingerprint",
                 "xhttp_path", "ss_method", "hy_obfs", "hy_masquerade", "ports", "protocols", "relays",
                 "relay_token", "steal_domain", "panel_domain", "main_name", "main_country", "hide_ip_new"]
EDITABLE_FIELDS = {"host", "sub_base_url", "reality_sni", "fingerprint", "hy_obfs", "hy_masquerade",
                   "protocols", "relays", "steal_domain", "panel_domain", "regru", "main_name", "main_country", "hide_ip_new"}
