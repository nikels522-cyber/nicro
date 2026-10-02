"""Usage:
  python -m app.cli admin <username> <password>   create/reset an admin
  python -m app.cli firewall off                  emergency: disable the panel IP allowlist
  python -m app.cli restore <backup.tar.gz> [--with-env]   restore (panel stopped); --with-env on a new server
  python -m app.cli info                          panel address and the commands for entry points / exit nodes
  python -m app.cli node-token <name>             one-time (1 h) token + command to add an exit node"""
import sys

from sqlalchemy import select

from . import settings_store
from .auth import hash_password
from .db import Admin, SessionLocal, init_db


def main():
    if sys.argv[1:2] == ["info"]:
        from . import config
        init_db()
        with SessionLocal() as db:
            s = settings_store.load(db)
        master = s["sub_base_url"].rstrip("/")
        print(f"PANEL={master}/{config.PANEL_PATH}/")
        print(f"RELAY_COMMAND={config.relay_command(master, s['relay_token'])}")
        return
    if sys.argv[1:2] == ["node-token"] and len(sys.argv) >= 3:
        import asyncio
        from .cluster import create_join_token_for
        init_db()
        print(asyncio.run(create_join_token_for(" ".join(sys.argv[2:])))["command"])
        return
    if sys.argv[1:] == ["firewall", "off"]:
        init_db()
        with SessionLocal() as db:
            s = settings_store.load(db)
            s["panel_fw"] = {**s["panel_fw"], "enabled": False}
            settings_store.save(db, s)
        print("panel firewall disabled; restart: systemctl restart vpnpanel")
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "restore":
        from pathlib import Path
        from .backup import restore_file
        restore_file(Path(sys.argv[2]), with_env="--with-env" in sys.argv)
        print("restored; start the panel: systemctl start vpnpanel")
        return
    if len(sys.argv) != 4 or sys.argv[1] != "admin":
        print(__doc__)
        sys.exit(1)
    _, _, username, password = sys.argv
    init_db()
    with SessionLocal() as db:
        admin = db.scalar(select(Admin).where(Admin.username == username))
        if admin:
            admin.password_hash = hash_password(password)
        else:
            db.add(Admin(username=username, password_hash=hash_password(password)))
        db.commit()
        settings_store.load(db)  # generates Reality keys etc. on first run
    print(f"admin '{username}' saved")


if __name__ == "__main__":
    main()
