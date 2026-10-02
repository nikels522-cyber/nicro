"""Panel firewall: only allowed client IPs can reach the panel UI and API.

Subscriptions (/sub/...) stay public — clients need them. Blocked requests get a plain 404, so
the panel looks absent. The client IP comes from Caddy (uvicorn trusts X-Forwarded-For only
from 127.0.0.1). "via_vpn" allows the server's own IP: an admin connected to our VPN reaches the
panel from it, which is how to manage from a phone on mobile internet with changing IPs."""
import ipaddress
import time
from collections import deque


def parse_net(value: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    return ipaddress.ip_network(value.strip(), strict=False)


class PanelFirewall:
    def __init__(self):
        self.enabled = False
        self.nets: list = []
        self.denied: deque[dict] = deque(maxlen=30)

    def load(self, s: dict):
        fw = s.get("panel_fw") or {}
        nets = []
        for r in fw.get("allow", []):
            try:
                nets.append(parse_net(r["cidr"]))
            except (ValueError, KeyError):
                pass
        if fw.get("via_vpn"):
            try:
                nets.append(parse_net(s["host"]))
            except ValueError:
                pass
        self.nets = nets
        self.enabled = bool(fw.get("enabled")) and bool(nets)  # an empty list never locks everyone out

    def allowed(self, ip: str, nets: list | None = None) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if addr.is_loopback:
            return True
        addr = getattr(addr, "ipv4_mapped", None) or addr
        return any(addr in n for n in (self.nets if nets is None else nets))

    def check(self, ip: str, path: str) -> bool:
        if not self.enabled or self.allowed(ip):
            return True
        self.denied.appendleft({"ip": ip, "ts": int(time.time()), "path": path[:80]})
        return False


firewall = PanelFirewall()
