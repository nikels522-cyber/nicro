"""Cloudflare WARP as a second exit of Xray: selected services (ChatGPT, Gemini, Netflix, ...) that refuse
datacenter IPs see a Cloudflare address instead. A free WARP account is registered once (WireGuard key
pair + Cloudflare's reply) and kept in settings ext.warp.account; cores/xray.py adds the wireguard
outbound and a routing rule for the chosen domains."""
import base64
from datetime import datetime, timezone

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from . import settings_store
from .db import SessionLocal

API = "https://api.cloudflareclient.com/v0a2158/reg"
PEER_PUBLIC = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
ENDPOINT = "162.159.192.1:2408"


def _keys() -> tuple[str, str]:
    priv = X25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode(), base64.b64encode(pub).decode()


async def register() -> dict:
    priv, pub = _keys()
    body = {"key": pub, "install_id": "", "fcm_token": "", "model": "PC", "type": "Android", "locale": "en_US",
            "tos": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(API, json=body, headers={"CF-Client-Version": "a-6.10-2158", "User-Agent": "okhttp/3.12.1"})
        data = r.json()
        cfg = data["config"]
    except (httpx.HTTPError, ValueError, KeyError) as e:
        raise RuntimeError(f"Не удалось зарегистрировать WARP: {e}")
    peer = cfg["peers"][0]
    addr = cfg["interface"]["addresses"]
    reserved = list(base64.b64decode(cfg.get("client_id", "AAAA")))[:3]
    return {"private_key": priv, "peer_public": peer.get("public_key") or PEER_PUBLIC,
            "address": [f"{addr['v4']}/32"] + ([f"{addr['v6']}/128"] if addr.get("v6") else []),
            "reserved": reserved, "endpoint": ENDPOINT, "id": data.get("id", "")}


async def ensure_account() -> dict:
    with SessionLocal() as db:
        s = settings_store.load(db)
        acc = settings_store.ext(s, "warp").get("account")
    if acc:
        return acc
    acc = await register()
    with SessionLocal() as db:
        s = settings_store.load(db)
        s.setdefault("ext", {}).setdefault("warp", {})["account"] = acc
        settings_store.save(db, s)
    return acc


def outbound(acc: dict) -> dict:
    return {"protocol": "wireguard", "tag": "warp",
            "settings": {"secretKey": acc["private_key"], "address": acc["address"],
                         "peers": [{"publicKey": acc["peer_public"], "endpoint": acc["endpoint"],
                                    "allowedIPs": ["0.0.0.0/0", "::/0"]}],
                         "reserved": acc["reserved"], "mtu": 1280}}


def rule(domains: list[str]) -> dict:
    return {"type": "field", "domain": [f"domain:{d}" for d in domains], "outboundTag": "warp"}
