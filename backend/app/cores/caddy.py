"""Camouflage website for self-steal REALITY / MTProto fronting.

Caddy serves a real site with Let's Encrypt certificates for our own domains on 127.0.0.1:8444
(the REALITY target) and on plain HTTP :80 (which also answers the ACME HTTP-01 challenge;
relays forward port 80 here, so relay domains get certificates too)."""
from .. import config
from . import systemctl

INDEX = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}</title>
<style>body{margin:0;font:16px/1.6 system-ui,sans-serif;color:#222;background:#fafafa;display:grid;place-items:center;min-height:100vh}
main{max-width:560px;padding:32px;text-align:center}h1{margin:0 0 8px;font-size:36px}p{color:#666}</style>
</head><body><main><h1>{name}</h1><p>Личная страница. Сайт в разработке — заходите позже.</p></main></body></html>
"""


def panel_block(domain: str, port: int) -> str:
    """The panel + subscriptions on the admin's own domain (next to the default sslip.io one)."""
    return f"""
{domain}:{port} {{
\t@internal path /internal/*
\trespond @internal 404
\tencode zstd gzip
\t@assets path */assets/*
\theader @assets Cache-Control "public, max-age=31536000, immutable"
\treverse_proxy 127.0.0.1:{config.LISTEN_PORT}
\theader -Server
}}
"""


def site_config(names: list[str]) -> str:
    port = config.STEAL_TARGET.rsplit(":", 1)[1]
    https = ", ".join(f"https://{n}:{port}" for n in names)
    http = ", ".join(f"http://{n}" for n in names)
    root = config.STEAL_WWW
    return f"""# managed by vpnpanel — camouflage site for self-steal REALITY
{https} {{
\tbind 127.0.0.1
\troot * {root}
\tfile_server
\theader -Server
}}

{http} {{
\troot * {root}
\tfile_server
\theader -Server
}}
"""


class Caddy:
    def __init__(self):
        self.applied: list[str] | None = None

    async def apply(self, names: list[str], panel_domain: str = "", panel_port: int = 2053):
        key = names + [f"panel:{panel_domain}:{panel_port}"]
        if key == self.applied:
            return
        config.STEAL_WWW.mkdir(parents=True, exist_ok=True)
        index = config.STEAL_WWW / "index.html"
        if not index.exists():
            # a plain personal page named after the domain (written once; edit the file freely)
            name = names[0].split(".")[-2] if names and names[0].count(".") else "Home"
            index.write_text(INDEX.replace("{name}", name))
        config.CADDY_SITE_FILE.parent.mkdir(parents=True, exist_ok=True)
        new = (site_config(names) if names else "") + (panel_block(panel_domain, panel_port) if panel_domain else "")
        old = config.CADDY_SITE_FILE.read_text() if config.CADDY_SITE_FILE.exists() else None
        if new != old:
            config.CADDY_SITE_FILE.write_text(new)
            await systemctl("reload", "caddy")
        self.applied = key


caddy = Caddy()
