"""Client share links and subscription payload."""
import base64
import re
from datetime import timezone
from urllib.parse import quote, urlencode

from . import config
from .db import User
from .settings_store import hy_cert_pin


def _fmt_host(h: str) -> str:
    return f"[{h}]" if ":" in h else h


def entry_points(s: dict) -> list[dict]:
    """Relays (cascade entries, e.g. a box with a Russian IP forwarding to this server) come
    first: they also work on mobile networks where direct foreign-hosting IPs are throttled."""
    relays = [{"id": f"r{i}", "name": r["name"], "host": r["host"], "domain": r.get("domain", "")}
              for i, r in enumerate(s.get("relays", [])) if r.get("host")]
    if relays:  # failover: an entry point that is down for minutes leaves subscriptions (health.py)
        from .health import dead_entries
        dead = dead_entries()[0]
        relays = [r for r in relays if r["host"] not in dead]
    return relays + [{"id": "", "name": "", "host": s["host"], "domain": s.get("steal_domain", "")}]


def user_links(u: User, s: dict, device=None, hide_failed: bool = True) -> list[dict]:
    """Share links for a user; with `device` (a registered Device) they carry its own credentials.
    Keys the blocking monitor found unreachable from Russia are left out (probe.py)."""
    uuid, ss_key = (device.uuid, device.ss_key) if device else (u.uuid, u.ss_key)
    p, ports = s["protocols"], s["ports"]
    reality = {"security": "reality", "pbk": s["reality_public"], "fp": s["fingerprint"],
               "sni": s["reality_sni"], "sid": s["short_id"]}
    pin = hy_cert_pin()
    links = []
    for ep in entry_points(s):
        # hide_ip: the entry point's own domain (resolves to the same IP) instead of the bare address
        host = _fmt_host(ep["domain"] if getattr(u, "hide_ip", False) and ep["domain"] else ep["host"])
        # the name shows up in client apps, so it must say the route and where to use the key
        from .settings_store import flag
        mf = flag(s.get("main_country", ""))
        route = f"🇷🇺→{mf} мобильный · через {ep['name']}" if ep["name"] else f"{mf} Wi-Fi/дом · напрямую"

        def add(key: str, protocol: str, url: str, label: str, podkop: bool):
            name = f"{route} · {label} · {u.username}"
            links.append({"key": f"{key}@{ep['id']}" if ep["id"] else key, "protocol": protocol,
                          "via": ep["name"] or "", "kind": "relay" if ep["name"] else "direct",
                          "host": ep["host"], "podkop": podkop, "name": name, "url": f"{url}#{quote(name)}"})

        if p.get("steal") and ep["domain"]:
            # own domain resolving to this very entry IP + real certificate: survives DPI that
            # flags SNI/IP mismatch (mobile operators). Listed first so clients prefer it.
            own = {**reality, "sni": ep["domain"]}
            q = {"type": "tcp", "encryption": "none", "flow": "xtls-rprx-vision", **own}
            add("steal", "VLESS Reality · свой домен",
                f"vless://{uuid}@{host}:{ports['steal']}?{urlencode(q)}", "Reality🛡домен", True)
            q = {"type": "xhttp", "encryption": "none", "path": s["xhttp_path"], "mode": "auto", **own}
            add("steal_x", "VLESS XHTTP · свой домен",
                f"vless://{uuid}@{host}:{ports['steal_xhttp']}?{urlencode(q)}", "XHTTP🛡домен", False)
        if p.get("vless"):
            q = {"type": "tcp", "encryption": "none", "flow": "xtls-rprx-vision", **reality}
            add("vless", "VLESS Reality Vision", f"vless://{uuid}@{host}:{ports['vless']}?{urlencode(q)}",
                "Reality", True)
        if p.get("xhttp"):  # xray-only: sing-box (Podkop, HomeProxy) has no XHTTP transport
            q = {"type": "xhttp", "encryption": "none", "path": s["xhttp_path"], "mode": "auto", **reality}
            add("xhttp", "VLESS XHTTP Reality", f"vless://{uuid}@{host}:{ports['xhttp']}?{urlencode(q)}",
                "XHTTP", False)
        if p.get("hy"):
            q = {"sni": s["reality_sni"], "insecure": "1"}
            if pin:
                q["pinSHA256"] = pin
            if s["hy_obfs"]:
                q.update({"obfs": "salamander", "obfs-password": s["hy_obfs_password"]})
            add("hy", "Hysteria2 (QUIC)",
                f"hysteria2://{quote(u.hy_password)}@{host}:{ports['hy']}/?{urlencode(q)}", "Hysteria2", True)
        if p.get("ss"):
            userinfo = base64.b64encode(f"{s['ss_method']}:{s['ss_server_key']}:{ss_key}".encode()).decode()
            add("ss", "Shadowsocks 2022", f"ss://{userinfo}@{host}:{ports['ss']}", "SS2022", True)
    links += node_links(u, s, uuid)
    if hide_failed:
        from .probe import hidden_keys
        hidden = hidden_keys()
        links = [x for x in links if x["key"] not in hidden]
    return links


def node_links(u: User, s: dict, uuid: str) -> list[dict]:
    """Keys for every enabled cluster node: own-domain REALITY with the node's keys (cluster.py)."""
    from .cluster import enabled_nodes, flag  # late import: cluster imports the cores

    from .health import dead_entries
    dead = dead_entries()[1]
    out = []
    for n in enabled_nodes():
        if n.id in dead:
            continue
        addr = n.domain if getattr(u, "hide_ip", False) and n.domain and not n.domain.endswith(".sslip.io") else n.address
        host, route = _fmt_host(addr), f"{flag(n.country)} {n.name}"
        base = {"security": "reality", "pbk": n.reality_public, "fp": s["fingerprint"], "sni": n.domain,
                "sid": n.short_id}
        for key, protocol, label, port, q, podkop in (
            ("steal", "VLESS Reality · свой домен", "Reality🛡", n.ports["vision"],
             {"type": "tcp", "encryption": "none", "flow": "xtls-rprx-vision"}, True),
            ("steal_x", "VLESS XHTTP · свой домен", "XHTTP🛡", n.ports["xhttp"],
             {"type": "xhttp", "encryption": "none", "path": s["xhttp_path"], "mode": "auto"}, False),
        ):
            name = f"{route} · {label} · {u.username}"
            out.append({"key": f"{key}@n{n.id}", "protocol": protocol, "via": f"{flag(n.country)} {n.name}",
                        "kind": "node", "host": n.address, "podkop": podkop, "name": name,
                        "url": f"vless://{uuid}@{host}:{port}?{urlencode({**q, **base})}#{quote(name)}"})
    return out


def telegram_proxy(s: dict) -> dict:
    """MTProto (Fake-TLS) proxy links, one per entry point. Entry points with an own domain get
    a dedicated mtg instance fronted by that domain (see cores/mtg.py)."""
    from .cores.mtg import instances, secret_for

    if not s.get("ext", {}).get("mtproto", {}).get("enabled", True):
        return {"enabled": False, "links": []}
    try:
        text = config.MTG_CONFIG.read_text()
    except OSError:
        return {"enabled": False, "links": []}
    secret = re.search(r'^\s*secret\s*=\s*"([^"]+)"', text, re.M)
    bind = re.search(r'^\s*bind-to\s*=\s*"[^"]*:(\d+)"', text, re.M)
    if not secret or not bind:
        return {"enabled": False, "links": []}
    default = (int(bind.group(1)), secret.group(1))
    by_host = {i.get("relay_host", s["host"]): (i["port"], secret_for(s, i["domain"])) for i in instances(s)}
    links = []
    for ep in entry_points(s):
        port, sec = by_host.get(ep["host"], default)
        q = urlencode({"server": ep["host"], "port": port, "secret": sec})
        links.append({"via": ep["name"], "host": ep["host"], "port": port, "domain": ep["domain"],
                      "tg": f"tg://proxy?{q}", "https": f"https://t.me/proxy?{q}"})
    return {"enabled": True, "links": links}


def sub_url(u: User, s: dict) -> str:
    return f"{s['sub_base_url'].rstrip('/')}/sub/{u.sub_token}"


def subscription_body(u: User, s: dict, device=None) -> str:
    text = "\n".join(link["url"] for link in user_links(u, s, device))
    return base64.b64encode(text.encode()).decode()


def subscription_headers(u: User, s: dict | None = None) -> dict:
    info = f"upload={u.used_up}; download={u.used_down}; total={u.data_limit}"
    if u.expire_at:  # expire=0 is shown as 01.01.1970 by some clients (Hiddify); omit when unlimited
        info += f"; expire={int(u.expire_at.replace(tzinfo=timezone.utc).timestamp())}"
    return {
        "subscription-userinfo": info,
        "profile-title": "base64:" + base64.b64encode(f"nicro · {u.username}".encode()).decode(),
        "profile-update-interval": "1",
        "content-disposition": f'attachment; filename="{u.username}"',
        **_app_headers(u, s),
    }


def _app_headers(u: User, s: dict | None) -> dict:
    """Happ & co.: a "support" button that opens our bot already bound to this client, and a link to
    the client's web page (status, instructions)."""
    if not s:
        return {}
    from .telegram import invite_link
    h = {"profile-web-page-url": f"{sub_url(u, s)}?page=1"}
    routing = happ_routing(s)
    if routing:
        h["routing"] = routing
    inv = invite_link(u)
    if inv:
        h["support-url"] = inv
    return h


def happ_routing(s: dict) -> str | None:
    """Happ routing profile (Дополнения → Маршрутизация): sites of Russia go direct, the rest through
    the VPN. Delivered in the `routing` subscription header; Happ applies it on update."""
    from .settings_store import ext
    import json
    cfg = ext(s, "routing")
    if not cfg["enabled"]:
        return None
    extra = [d.strip() for d in cfg.get("extra_direct", []) if d.strip()]
    profile = {
        "Name": "nicro-RU", "GlobalProxy": "true", "UseChunkFiles": "true",
        "RemoteDNSType": "DoH", "RemoteDNSDomain": "https://cloudflare-dns.com/dns-query", "RemoteDNSIP": "1.1.1.1",
        "DomesticDNSType": "DoU", "DomesticDNSDomain": "", "DomesticDNSIP": "77.88.8.8",
        "Geoipurl": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat",
        "Geositeurl": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat",
        "LastUpdated": "", "DnsHosts": {},
        "DirectSites": ["geosite:category-ru", "geosite:private", "domain:ru", "domain:su", "domain:xn--p1ai"]
                       + [x if ":" in x else f"domain:{x}" for x in extra],
        "DirectIp": ["geoip:ru", "geoip:private"],
        "ProxySites": [], "ProxyIp": [], "BlockSites": [], "BlockIp": [],
        "DomainStrategy": "IPIfNonMatch", "FakeDNS": "false",
    }
    return "happ://routing/onadd/" + base64.b64encode(json.dumps(profile, ensure_ascii=False).encode()).decode()
