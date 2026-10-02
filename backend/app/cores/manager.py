"""Keeps the running cores in sync with the DB and collects per-user traffic."""
import asyncio
from urllib.parse import urlparse
import time

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from .. import settings_store
from ..db import Device, SessionLocal, TrafficDaily, User, device_email, owner_of, today, utcnow
from . import log
from .caddy import caddy
from .devices import devices
from .hysteria import hy_id, hysteria
from .mtg import mtg
from .xray import Creds, xray


PROBE_EMAIL = "nicro-probe@system"  # hidden identity of probe.py (not a user)


class CoreManager:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.online: dict[str, float] = {}  # username -> last seen unix time (in-memory)

    @staticmethod
    def active_state():
        """(full settings, core settings, active users, Xray creds, device identities) — shared by
        the local cores and the cluster node configs (cluster.py)."""
        with SessionLocal() as db:
            full = settings_store.load(db)
            s = settings_store.core_view(full)
            now = utcnow()
            everyone = {u.id: u for u in db.scalars(select(User))}
            # family members work while both they and the head of the family are active
            users = [u for u in everyone.values() if u.status(now) == "active"
                     and (not u.parent_id or u.parent_id not in everyone or everyone[u.parent_id].status(now) == "active")]
            devs = db.scalars(select(Device).where(Device.enabled, Device.user_id.in_([u.id for u in users])))
            by_user: dict[int, list[Device]] = {}
            for d in devs:
                by_user.setdefault(d.user_id, []).append(d)
        creds = [Creds(u.username, u.uuid, u.ss_key) for u in users]
        creds += [Creds(device_email(d.id, u.username), d.uuid, d.ss_key)
                  for u in users for d in by_user.get(u.id, [])]
        creds.append(Creds(PROBE_EMAIL, full["probe_uuid"], full["probe_ss_key"]))  # blocking monitor
        from ..speed import mark_of
        limited = [u for u in users if u.speed_mbps] if settings_store.ext(full, "speed")["enabled"] else []
        # speed.py: mark -> Xray identities of the client (its devices too); the limit itself is in full["_speed"]
        s["speed"] = {str(mark_of(u.id)): [u.username] + [device_email(d.id, u.username) for d in by_user.get(u.id, [])]
                      for u in limited} or None
        full["_speed"] = {mark_of(u.id): u.speed_mbps for u in limited}
        identities = [(u.username, u.multi_device, [device_email(d.id, u.username) for d in by_user.get(u.id, [])])
                      for u in users]
        return full, s, users, creds, identities

    async def sync(self, force_restart: bool = False):
        async with self.lock:
            full, s, users, creds, identities = self.active_state()
            panel_port = urlparse(full["sub_base_url"]).port or 2053
            await caddy.apply(s["steal_names"], full.get("panel_domain", ""), panel_port)  # REALITY targets it
            if await xray.apply(s, creds, force_restart):
                devices.reset()  # API-added routing rules die with the process
                await asyncio.sleep(1.5)  # let the API come up before re-adding them
            await devices.enforce(identities)
            from ..speed import shaper
            await shaper.apply(full["_speed"])
            await mtg.apply(full)
            from .. import l2tp
            await l2tp.sync(users)
            await hysteria.apply(s, {hy_id(u.username, u.hy_password) for u in users}, force_restart)

    async def collect(self):
        """Pull traffic counters from the local cores and add them to the DB."""
        with SessionLocal() as db:
            s = settings_store.load(db)
        for part in (await xray.pull_traffic(), await hysteria.pull_traffic(s)):
            self.add_traffic(part)

    def add_traffic(self, part: dict[str, list[int]]):
        """Adds per-identity [up, down] byte deltas (local cores or a cluster node's report)."""
        totals: dict[str, list[int]] = {}
        active_devices: set[int] = set()
        for email, (up, down) in part.items():
            name = owner_of(email)  # device identities count towards their user
            if (up or down) and "@d" in email:
                active_devices.add(int(email.rsplit("@d", 1)[1]))
            t = totals.setdefault(name, [0, 0])
            t[0] += up
            t[1] += down
        totals = {n: v for n, v in totals.items() if v[0] or v[1]}
        if not totals:
            return
        now = utcnow()
        day = today()
        with SessionLocal() as db:
            for d in db.scalars(select(Device).where(Device.id.in_(active_devices))):
                d.last_online = now
            users = {u.username: u for u in db.scalars(select(User).where(User.username.in_(totals)))}
            for name, (up, down) in totals.items():
                u = users.get(name)
                if not u:
                    continue
                u.used_up += up
                u.used_down += down
                if u.parent_id:  # family: the traffic also counts towards the shared limit of the head
                    head = db.get(User, u.parent_id)
                    if head:
                        head.used_up += up
                        head.used_down += down
                u.last_online = now
                self.online[name] = time.time()
                stmt = insert(TrafficDaily).values(user_id=u.id, day=day, up=up, down=down)
                db.execute(stmt.on_conflict_do_update(
                    index_elements=["user_id", "day"],
                    set_={"up": TrafficDaily.up + up, "down": TrafficDaily.down + down}))
            db.commit()

    async def loop(self, interval: int):
        with SessionLocal() as db:
            s = settings_store.load(db)
        if not s.get("main_country"):
            s = await settings_store.detect_main(s)
            if s.get("main_country"):
                with SessionLocal() as db:
                    cur = settings_store.load(db)
                    cur.update(main_country=s["main_country"], main_name=cur.get("main_name") or s["main_name"])
                    settings_store.save(db, cur)
        await self.sync(force_restart=True)
        while True:
            await asyncio.sleep(interval)
            try:
                await self.collect()
                await self.sync()  # applies expirations / limits
            except Exception:
                log.exception("stats loop iteration failed")


manager = CoreManager()
