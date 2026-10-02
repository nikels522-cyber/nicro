import os
from pathlib import Path

DATA_DIR = Path(os.getenv("VPNPANEL_DATA", "/opt/vpnpanel/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_URL = f"sqlite:///{DATA_DIR / 'panel.db'}"

FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", "/opt/vpnpanel/frontend"))

# Secret URL prefix of the panel (the panel is not reachable without it)
PANEL_PATH = os.getenv("PANEL_PATH", "panel").strip("/")
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "change-me")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8000"))

# Public values used for first-run defaults
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "127.0.0.1")
SUB_BASE_URL = os.getenv("SUB_BASE_URL", f"http://{PUBLIC_HOST}:{LISTEN_PORT}")

XRAY_BIN = os.getenv("XRAY_BIN", "/usr/local/bin/xray")
XRAY_CONFIG = Path(os.getenv("XRAY_CONFIG", "/usr/local/etc/xray/config.json"))
XRAY_API = os.getenv("XRAY_API", "127.0.0.1:10085")
XRAY_SERVICE = "xray"

HY_CONFIG = Path(os.getenv("HY_CONFIG", "/etc/hysteria/config.yaml"))
HY_CERT = Path(os.getenv("HY_CERT", "/etc/hysteria/server.crt"))
HY_KEY = Path(os.getenv("HY_KEY", "/etc/hysteria/server.key"))
HY_STATS_LISTEN = "127.0.0.1:9999"
HY_SERVICE = "hysteria-server"

# Camouflage site with real certificates for our own domains (Caddy), used as the REALITY target
STEAL_TARGET = "127.0.0.1:8444"
CADDY_SITE_FILE = Path("/etc/caddy/sites/steal.caddy")
STEAL_WWW = Path("/var/www/steal")

MTG_CONFIG = Path(os.getenv("MTG_CONFIG", "/etc/mtg.toml"))  # Telegram MTProto proxy (Fake-TLS)
MTG_SERVICE = "mtg"

MANAGED_SERVICES = [XRAY_SERVICE, HY_SERVICE, MTG_SERVICE, "caddy"]

STATS_INTERVAL = 10  # seconds between traffic collection / limit enforcement
MONITOR_INTERVAL = 2  # seconds between system metric samples

# where the installers live (one-line commands shown in the panel)
REPO = os.getenv("NICRO_REPO", "nikels522-cyber/nicro")
RAW = f"https://raw.githubusercontent.com/{REPO}/main"


def relay_command(master: str, token: str) -> str:
    return f"curl -fsSL {RAW}/install-relay.sh | sudo bash -s -- --master {master} --token {token}"


def node_command(master: str, token: str) -> str:
    return f"curl -fsSL {RAW}/install-node.sh | sudo bash -s -- --master {master} --token {token}"


_http = None


def http():
    """One shared HTTP client for frequent calls (Telegram, relay agents): creating a client per request
    builds a new TLS context each time, which was a visible share of the panel's CPU."""
    global _http
    import httpx
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(40, connect=8),
                                  limits=httpx.Limits(max_connections=50, max_keepalive_connections=10))
    return _http

