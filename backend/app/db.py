from datetime import date, datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import DB_URL

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(conn, _):
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(engine, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today() -> date:
    return utcnow().date()


class Base(DeclarativeBase):
    pass


class Admin(Base):
    __tablename__ = "admins"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    # owner: everything; operator: clients, devices, plans, payments; viewer: read-only (auth.py)
    role: Mapped[str] = mapped_column(String(16), default="owner", server_default="owner")
    totp_secret: Mapped[str] = mapped_column(String(64), default="", server_default="")  # 2FA (totp.py)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    tg_id: Mapped[str] = mapped_column(String(32), default="", server_default="")  # admin bot commands/alerts


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    uuid: Mapped[str] = mapped_column(String(36))
    ss_key: Mapped[str] = mapped_column(String(64))
    hy_password: Mapped[str] = mapped_column(String(64), index=True)
    sub_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    data_limit: Mapped[int] = mapped_column(BigInteger, default=0)  # bytes, 0 = unlimited
    expire_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_up: Mapped[int] = mapped_column(BigInteger, default=0)
    used_down: Mapped[int] = mapped_column(BigInteger, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    # False = only one device (source IP) may be online at a time, see cores/devices.py
    multi_device: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # Telegram chat id for notifications (see telegram.py) and which ones were already sent
    tg_id: Mapped[str] = mapped_column(String(32), default="", server_default="")
    notified: Mapped[dict] = mapped_column(JSON, default=dict)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id", ondelete="SET NULL"), nullable=True)
    reset_monthly: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # traffic every 30 days
    # L2TP/IPsec extension (l2tp.py): login = username
    l2tp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    l2tp_password: Mapped[str] = mapped_column(String(64), default="", server_default="")
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # family: members share the parent's period and traffic limit (their traffic counts for the parent too)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # referral program (growth.py): who invited this client, and whether the reward was already given
    referred_by: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ref_rewarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    promo_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # discount waiting for the next payment
    speed_mbps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 0 = no limit (speed.py)
    # keys carry the entry point's domain instead of its IP address (links.py); on for clients created since
    # this option exists (settings "hide_ip_new"), existing clients keep their links unchanged
    hide_ip: Mapped[bool] = mapped_column(Boolean, default=True, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_online: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def used(self) -> int:
        return self.used_up + self.used_down

    def status(self, now: datetime | None = None) -> str:
        now = now or utcnow()
        if not self.enabled:
            return "disabled"
        if self.expire_at and self.expire_at <= now:
            return "expired"
        if self.data_limit and self.used >= self.data_limit:
            return "limited"
        return "active"


class Device(Base):
    """A client device registered when it fetched the subscription with a hardware ID (x-hwid,
    sent by Happ, v2RayTun, ...). Each device gets its own credentials, so Xray sees it as a
    separate identity (email `<username>@d<id>`) and devices are counted exactly, even behind one IP."""
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("user_id", "hwid"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    hwid: Mapped[str] = mapped_column(String(128))
    uuid: Mapped[str] = mapped_column(String(36))
    ss_key: Mapped[str] = mapped_column(String(64))
    os: Mapped[str] = mapped_column(String(64), default="")
    os_version: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    app: Mapped[str] = mapped_column(String(128), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_sub_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_online: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def device_email(device_id: int, username: str) -> str:
    return f"{username}@d{device_id}"


def owner_of(email: str) -> str:
    """Xray email -> username (device identities are `<username>@d<id>`)."""
    return email.split("@d", 1)[0]


class Plan(Base):
    """A tariff: what a user gets when created/extended with it. `price` is ready for payments."""
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    days: Mapped[int] = mapped_column(Integer, default=30)  # 0 = no expiry
    data_limit_gb: Mapped[float] = mapped_column(Float, default=0)  # 0 = unlimited
    multi_device: Mapped[bool] = mapped_column(Boolean, default=True)
    reset_monthly: Mapped[bool] = mapped_column(Boolean, default=False)
    price: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    family_size: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # extra family members
    speed_mbps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 0 = no limit


class Payment(Base):
    """Every extension/payment of a user: manual now; online providers plug in via payments.py."""
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id", ondelete="SET NULL"), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    provider: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(16), default="paid")  # pending | paid | failed | canceled
    external_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    admin: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # promo, chat, provider details (payments.py)


class PromoCode(Base):
    """percent: discount on the next payment; days: free days right away (growth.py)."""
    __tablename__ = "promo_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="percent")  # percent | days
    value: Mapped[float] = mapped_column(Float, default=10)
    max_uses: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited
    used: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PromoUse(Base):
    __tablename__ = "promo_uses"
    __table_args__ = (UniqueConstraint("promo_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BotChat(Base):
    """Everyone who wrote to the bot, with or without an account (referral arrival, support)."""
    __tablename__ = "bot_chats"
    chat_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    tg_username: Mapped[str] = mapped_column(String(64), default="")
    ref_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # came via a referral link
    lang: Mapped[str] = mapped_column(String(8), default="", server_default="")  # i18n.py; "" = not detected yet
    # support conversation with this chat (support.py): open -> answered -> closed; who took it
    support_status: Mapped[str] = mapped_column(String(12), default="", server_default="")
    support_assignee: Mapped[str] = mapped_column(String(64), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SupportMessage(Base):
    """Support conversation through the bot (support.py)."""
    __tablename__ = "support_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    direction: Mapped[str] = mapped_column(String(4))  # in | out
    text: Mapped[str] = mapped_column(Text)
    admin: Mapped[str] = mapped_column(String(64), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    tg_refs: Mapped[dict] = mapped_column(JSON, default=dict)  # {admin chat: message id} for reply-to
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class HealthDaily(Base):
    """Per-server availability samples, one row per server and day (status page, reports)."""
    __tablename__ = "health_daily"
    server: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    ok: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    admin: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(128), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


class Node(Base):
    """A cluster node: an extra exit server running Xray + the nicro node agent. It joined with a
    one-time token and authenticates with its own secret (only the hash is stored). It pulls its
    Xray config from the master and reports traffic / online devices / metrics (cluster.py)."""
    __tablename__ = "nodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    address: Mapped[str] = mapped_column(String(253))  # public IP/host used in client links
    domain: Mapped[str] = mapped_column(String(253))  # own-domain REALITY SNI (default <ip>.sslip.io)
    country: Mapped[str] = mapped_column(String(8), default="")
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    reality_private: Mapped[str] = mapped_column(String(64))
    reality_public: Mapped[str] = mapped_column(String(64))
    short_id: Mapped[str] = mapped_column(String(16))
    ports: Mapped[dict] = mapped_column(JSON, default=dict)  # {"vision": 443, "xhttp": 8443}
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    info: Mapped[dict] = mapped_column(JSON, default=dict)  # last metrics / versions from the agent


class JoinToken(Base):
    __tablename__ = "join_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    domain: Mapped[str] = mapped_column(String(253), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class TrafficDaily(Base):
    __tablename__ = "traffic_daily"
    __table_args__ = (UniqueConstraint("user_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    up: Mapped[int] = mapped_column(BigInteger, default=0)
    down: Mapped[int] = mapped_column(BigInteger, default=0)


class ServerDaily(Base):
    __tablename__ = "server_daily"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    rx: Mapped[int] = mapped_column(BigInteger, default=0)
    tx: Mapped[int] = mapped_column(BigInteger, default=0)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


# columns added after the first release: (table, column, DDL)
_MIGRATIONS = [
    ("users", "multi_device", "BOOLEAN NOT NULL DEFAULT 1"),
    ("users", "tg_id", "VARCHAR(32) NOT NULL DEFAULT ''"),
    ("users", "notified", "JSON NOT NULL DEFAULT '{}'"),
    ("users", "plan_id", "INTEGER REFERENCES plans(id) ON DELETE SET NULL"),
    ("users", "reset_monthly", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "last_reset_at", "DATETIME"),
    ("admins", "role", "VARCHAR(16) NOT NULL DEFAULT 'owner'"),
    ("users", "l2tp_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "l2tp_password", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("admins", "totp_secret", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("admins", "totp_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    ("admins", "tg_id", "VARCHAR(32) NOT NULL DEFAULT ''"),
    ("users", "parent_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
    ("users", "referred_by", "INTEGER"),
    ("users", "ref_rewarded", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "promo_id", "INTEGER"),
    ("users", "speed_mbps", "INTEGER NOT NULL DEFAULT 0"),
    ("plans", "family_size", "INTEGER NOT NULL DEFAULT 0"),
    ("plans", "speed_mbps", "INTEGER NOT NULL DEFAULT 0"),
    ("payments", "meta", "JSON NOT NULL DEFAULT '{}'"),
    ("bot_chats", "lang", "VARCHAR(8) NOT NULL DEFAULT ''"),
    ("bot_chats", "support_status", "VARCHAR(12) NOT NULL DEFAULT ''"),
    ("bot_chats", "support_assignee", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("users", "hide_ip", "BOOLEAN NOT NULL DEFAULT 0"),
]


def init_db():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table, column, ddl in _MIGRATIONS:
            cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
