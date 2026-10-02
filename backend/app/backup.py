"""Backups: a consistent copy of the database (+ /etc/vpnpanel.env) in a tar.gz, kept locally (last
`keep`) and sent to owners' Telegram daily. Restore: panel upload or CLI (`python -m app.cli restore
<file>`), which also works on a fresh server after install.sh — that is the disaster-recovery path."""
import asyncio
import io
import logging
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from . import config, settings_store
from .db import Admin, SessionLocal, utcnow

log = logging.getLogger("vpnpanel.backup")
BACKUP_DIR = config.DATA_DIR.parent / "backups"
ENV_FILE = Path("/etc/vpnpanel.env")
DB_FILE = config.DATA_DIR / "panel.db"
DEFAULTS = {"enabled": True, "hour": 4, "keep": 7, "telegram": True}


def settings() -> dict:
    with SessionLocal() as db:
        return {**DEFAULTS, **settings_store.load(db).get("backup", {})}


def make_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    name = f"nicro-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"
    path = BACKUP_DIR / name
    with tempfile.TemporaryDirectory() as d:
        copy = Path(d) / "panel.db"
        src = sqlite3.connect(DB_FILE)
        dst = sqlite3.connect(copy)
        with dst:
            src.backup(dst)  # consistent snapshot while the panel keeps running
        src.close()
        dst.close()
        with tarfile.open(path, "w:gz") as tar:
            tar.add(copy, arcname="panel.db")
            if ENV_FILE.exists():
                tar.add(ENV_FILE, arcname="vpnpanel.env")
    path.chmod(0o600)
    keep = settings()["keep"]
    for old in sorted(BACKUP_DIR.glob("ni*-*.tar.gz"), key=lambda p: p.stat().st_mtime)[:-keep]:
        old.unlink(missing_ok=True)
    return path


def list_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    return [{"name": p.name, "size": p.stat().st_size, "ts": int(p.stat().st_mtime)}
            for p in sorted(BACKUP_DIR.glob("ni*-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)]


def validate(data: bytes) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = tar.getnames()
    if "panel.db" not in names:
        raise ValueError("В архиве нет panel.db — это не бэкап nicro")


def restore_file(path: Path, with_env: bool = False):
    """Replaces the database (and optionally the env) from a backup. The panel must be stopped."""
    with tarfile.open(path, "r:gz") as tar:
        db = tar.extractfile("panel.db").read()
        env = tar.extractfile("vpnpanel.env").read() if with_env and "vpnpanel.env" in tar.getnames() else None
    if DB_FILE.exists():
        DB_FILE.rename(DB_FILE.with_suffix(f".before-restore-{int(time.time())}"))
    for suffix in ("-wal", "-shm"):
        Path(str(DB_FILE) + suffix).unlink(missing_ok=True)
    DB_FILE.write_bytes(db)
    if env:
        ENV_FILE.write_bytes(env)
        ENV_FILE.chmod(0o600)


def schedule_restore(data: bytes):
    """From the panel: stop, restore, start — in a detached systemd unit (the panel restarts)."""
    validate(data)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"upload-{int(time.time())}.tar.gz"
    path.write_bytes(data)
    app_dir = config.DATA_DIR.parent
    script = (f"sleep 2; systemctl stop vpnpanel; cd {app_dir} && set -a && . /etc/vpnpanel.env && set +a && "
              f"venv/bin/python -m app.cli restore {path}; systemctl start vpnpanel")
    subprocess.Popen(["systemd-run", "--unit", f"nicro-restore-{int(time.time())}", "bash", "-c", script])


async def send_to_owners(path: Path, caption: str) -> int:
    from .telegram import bot
    with SessionLocal() as db:
        chats = [a.tg_id for a in db.scalars(select(Admin).where(Admin.role == "owner", Admin.tg_id != ""))]
    sent = 0
    for chat in chats:
        try:
            await bot.send_document(chat, path, caption)
            sent += 1
        except Exception as e:
            log.warning("backup to telegram %s failed: %s", chat, e)
    return sent


async def run_backup(reason: str = "ежедневный") -> tuple[Path, int]:
    path = await asyncio.to_thread(make_backup)
    from . import storage
    clouds = await storage.upload_all(path, settings()["keep"])
    failed = [c for c in clouds if not c["ok"]]
    if failed:
        from .telegram import bot
        await bot.send_admins("🔴 <b>nicro:</b> бэкап не загрузился в " +
                              ", ".join(f"{c['name']} ({c['error'][:80]})" for c in failed))
    sent = 0
    if settings()["telegram"]:
        with SessionLocal() as db:
            from .db import User
            users = len(list(db.scalars(select(User.id))))
        sent = await send_to_owners(path, f"🗄 Бэкап nicro ({reason})\n{path.name} · клиентов: {users}\n"
                                          "Восстановление: панель → Безопасность → Бэкапы. Храните в личном чате — "
                                          "внутри ключи сервера.")
    log.info("backup %s, sent to %d chats, clouds %s", path.name, sent, clouds)
    return path, sent, clouds


async def loop():
    last_day = None
    while True:
        await asyncio.sleep(300)
        try:
            cfg = settings()
            now = datetime.now()
            if cfg["enabled"] and now.hour == cfg["hour"] and last_day != now.date():
                await run_backup()
                last_day = now.date()
        except Exception:
            log.exception("scheduled backup failed")
