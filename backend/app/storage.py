"""Cloud storages for backups via rclone: Yandex Disk, Mail.ru Cloud, Google Drive, Dropbox, OneDrive,
S3-compatible (Yandex Object Storage, VK Cloud, Selectel, AWS, Cloudflare R2, Backblaze), WebDAV
(Nextcloud...), SFTP. Every backup is uploaded to all enabled storages and old copies there are pruned
to the same `keep` count. Credentials stay in the panel DB; rclone gets a temporary config per run."""
import asyncio
import secrets
import tempfile
from pathlib import Path

from . import settings_store
from .cores import run
from .db import SessionLocal

# type -> (title, rclone backend, fields [(key, label, secret)], fixed options, help)
PROVIDERS = {
    "yandex_disk": ("Яндекс Диск", "webdav", [("user", "Логин Яндекса", False), ("pass", "Пароль приложения", True)],
                    {"url": "https://webdav.yandex.ru", "vendor": "other"},
                    "Пароль приложения: id.yandex.ru → Безопасность → Пароли приложений → «Файлы (WebDAV)»."),
    "mailru": ("Облако Mail.ru", "mailru", [("user", "Почта Mail.ru", False), ("pass", "Пароль приложения", True)], {},
               "Пароль приложения: Mail.ru → Безопасность → Пароли для внешних приложений (доступ к Облаку)."),
    "gdrive": ("Google Drive", "drive", [("token", "Токен rclone (JSON)", True)], {"scope": "drive.file"},
               "На компьютере установите rclone и выполните: rclone authorize \"drive\" — вставьте выданный JSON."),
    "dropbox": ("Dropbox", "dropbox", [("token", "Токен rclone (JSON)", True)], {},
                "На компьютере: rclone authorize \"dropbox\" — вставьте выданный JSON."),
    "onedrive": ("OneDrive", "onedrive", [("token", "Токен rclone (JSON)", True), ("drive_id", "Drive ID", False)],
                 {"drive_type": "personal"},
                 "На компьютере: rclone config → OneDrive; скопируйте token и drive_id из ~/.config/rclone/rclone.conf."),
    "s3": ("S3-хранилище", "s3", [("endpoint", "Endpoint (напр. storage.yandexcloud.net)", False),
                                  ("access_key_id", "Access key", False), ("secret_access_key", "Secret key", True),
                                  ("region", "Регион (напр. ru-central1)", False)], {"provider": "Other"},
           "Yandex Object Storage, VK Cloud, Selectel, AWS, Cloudflare R2, Backblaze B2 — укажите бакет в поле «Папка»."),
    "webdav": ("WebDAV", "webdav", [("url", "Адрес WebDAV", False), ("user", "Логин", False), ("pass", "Пароль", True)],
               {"vendor": "other"}, "Nextcloud, ownCloud, собственный сервер."),
    "sftp": ("SFTP (другой сервер)", "sftp", [("host", "Хост", False), ("user", "Пользователь", False),
                                              ("pass", "Пароль", True), ("port", "Порт", False)], {}, ""),
}
OBSCURED = {"pass"}  # rclone wants these obscured


def storages() -> list[dict]:
    with SessionLocal() as db:
        return list(settings_store.load(db).get("storages", []))


def public(st: dict) -> dict:
    """For the UI: secrets masked."""
    t = PROVIDERS.get(st["type"])
    secret_keys = {k for k, _, sec in (t[2] if t else []) if sec}
    return {**st, "params": {k: ("***" if k in secret_keys and v else v) for k, v in st.get("params", {}).items()}}


def save(items: list[dict]):
    with SessionLocal() as db:
        s = settings_store.load(db)
        old = {x["id"]: x for x in s.get("storages", [])}
        out = []
        for it in items:
            if it.get("type") not in PROVIDERS:
                raise ValueError(f"неизвестный тип хранилища: {it.get('type')}")
            sid = it.get("id") or secrets.token_hex(4)
            params = dict(it.get("params", {}))
            for k, v in list(params.items()):  # masked value = keep the stored one
                if v == "***":
                    params[k] = old.get(sid, {}).get("params", {}).get(k, "")
            out.append({"id": sid, "type": it["type"], "name": it.get("name") or PROVIDERS[it["type"]][0],
                        "enabled": bool(it.get("enabled", True)), "path": (it.get("path") or "nicro-backups").strip("/"),
                        "params": params})
        s["storages"] = out
        settings_store.save(db, s)
        return out


async def _config(st: dict) -> str:
    _title, backend, fields, fixed, _help = PROVIDERS[st["type"]]
    lines = [f"[r]", f"type = {backend}"] + [f"{k} = {v}" for k, v in fixed.items()]
    for key, _label, _sec in fields:
        val = str(st["params"].get(key, "")).strip()
        if not val:
            continue
        if key in OBSCURED:
            code, out, _ = await run("rclone", "obscure", val)
            val = out.strip() if code == 0 else val
        lines.append(f"{key} = {val}")
    return "\n".join(lines) + "\n"


async def _rclone(st: dict, *args: str, timeout: float = 300) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
        f.write(await _config(st))
    Path(f.name).chmod(0o600)
    try:
        code, out, err = await run("rclone", "--config", f.name, *args, timeout=timeout)
    finally:
        Path(f.name).unlink(missing_ok=True)
    return code, (out + err).strip()


async def upload(st: dict, path: Path, keep: int) -> str:
    code, out = await _rclone(st, "copyto", str(path), f"r:{st['path']}/{path.name}")
    if code != 0:
        raise RuntimeError(out[-300:])
    code, out = await _rclone(st, "lsf", f"r:{st['path']}", "--files-only")
    names = sorted(n for n in out.splitlines() if n.endswith(".tar.gz"))
    for old in names[:-keep]:
        await _rclone(st, "deletefile", f"r:{st['path']}/{old}")
    return "ok"


async def upload_all(path: Path, keep: int) -> list[dict]:
    results = []
    for st in storages():
        if not st["enabled"]:
            continue
        try:
            await upload(st, path, keep)
            results.append({"id": st["id"], "name": st["name"], "ok": True})
        except Exception as e:
            results.append({"id": st["id"], "name": st["name"], "ok": False, "error": str(e)})
    return results


async def test(sid: str) -> dict:
    st = next((x for x in storages() if x["id"] == sid), None)
    if not st:
        raise ValueError("хранилище не найдено")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("nicro storage test\n")
    name = f"nicro-test-{secrets.token_hex(3)}.txt"
    try:
        code, out = await _rclone(st, "copyto", f.name, f"r:{st['path']}/{name}", timeout=60)
        if code != 0:
            return {"ok": False, "error": out[-400:]}
        await _rclone(st, "deletefile", f"r:{st['path']}/{name}", timeout=60)
        return {"ok": True}
    finally:
        Path(f.name).unlink(missing_ok=True)


def catalog() -> list[dict]:
    return [{"type": k, "title": t, "fields": [{"key": a, "label": b, "secret": c} for a, b, c in f], "help": h}
            for k, (t, _b, f, _fx, h) in PROVIDERS.items()]
