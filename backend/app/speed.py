"""Per-client speed limits. Xray itself can't limit speed, so:

  1. every limited client gets its own copy of the "direct" outbound whose sockets carry a firewall
     mark (MARK_BASE + user id), see cores/xray.py (_skeleton, speed);
  2. upload (server -> internet): HTB on the main interface classifies by that mark (fw filter);
  3. download (internet -> server): the mark is saved into conntrack (iptables CONNMARK), restored
     on ingress by tc (act_connmark) and the packets are shaped on ifb0 the same way.
Verified live: a 5 Mbit/s client got 4.7 down / 4.6 up, others unaffected.

Unlimited traffic is never touched (HTB default 0 = pass unshaped); with no limited clients
everything is torn down. The limit applies to the client's traffic through this server, whatever
entry point (direct / Raspberry Pi) they use; family members get their own limit."""
import logging

from .cores import run

log = logging.getLogger("vpnpanel.speed")
MARK_BASE = 1000
IFB = "ifb0"


def mark_of(user_id: int) -> int:
    return MARK_BASE + user_id


async def _sh(*cmd: str) -> tuple[int, str]:
    code, out, err = await run(*cmd)
    return code, (out + err).strip()


class Shaper:
    def __init__(self):
        self.applied: dict[int, int] | None = None  # mark -> mbps
        self.iface = ""

    async def _iface(self) -> str:
        if not self.iface:
            _, out = await _sh("ip", "-o", "route", "show", "default")
            parts = out.split()
            self.iface = parts[parts.index("dev") + 1] if "dev" in parts else "eth0"
        return self.iface

    async def _teardown(self, dev: str):
        await _sh("tc", "qdisc", "del", "dev", dev, "root")
        await _sh("tc", "qdisc", "del", "dev", dev, "ingress")
        await _sh("tc", "qdisc", "del", "dev", IFB, "root")
        await _sh("ip", "link", "set", IFB, "down")
        await _sh("iptables", "-t", "mangle", "-D", "OUTPUT", "-m", "mark", "!", "--mark", "0",
                  "-j", "CONNMARK", "--save-mark")

    async def apply(self, limits: dict[int, int]):
        """limits: {mark: mbps}. Rebuilds the qdiscs only when something changed."""
        if limits == self.applied:
            return
        dev = await self._iface()
        await self._teardown(dev)
        self.applied = dict(limits)
        if not limits:
            return
        await _sh("modprobe", "ifb")
        await _sh("ip", "link", "add", IFB, "type", "ifb")
        await _sh("ip", "link", "set", IFB, "txqueuelen", "1000")
        await _sh("ip", "link", "set", IFB, "up")
        await _sh("iptables", "-t", "mangle", "-A", "OUTPUT", "-m", "mark", "!", "--mark", "0",
                  "-j", "CONNMARK", "--save-mark")
        for d in (dev, IFB):
            code, out = await _sh("tc", "qdisc", "replace", "dev", d, "root", "handle", "1:", "htb", "default", "0")
            if code:
                log.warning("tc root on %s: %s", d, out)
                return
            for mark, mbps in limits.items():
                rate = f"{max(int(mbps), 1)}mbit"
                cls = f"1:{mark:x}"
                await _sh("tc", "class", "add", "dev", d, "parent", "1:", "classid", cls, "htb",
                          "rate", rate, "ceil", rate, "burst", "256k")
                await _sh("tc", "qdisc", "add", "dev", d, "parent", cls, "fq_codel")
                # "protocol all": on the ingress/ifb path "protocol ip" filters never match
                await _sh("tc", "filter", "add", "dev", d, "parent", "1:", "protocol", "all", "prio", "1",
                          "handle", str(mark), "fw", "flowid", cls)
        # ingress: restore the connection's mark and pass everything through ifb0, where only marked
        # packets have a class (unmarked ones leave unshaped through HTB default 0)
        await _sh("tc", "qdisc", "add", "dev", dev, "handle", "ffff:", "ingress")
        code, out = await _sh("tc", "filter", "add", "dev", dev, "parent", "ffff:", "protocol", "all", "prio", "1",
                              "matchall", "action", "connmark", "action", "mirred", "egress", "redirect", "dev", IFB)
        if code:
            log.warning("tc ingress filter: %s", out)
        log.info("speed limits applied: %s", {m - MARK_BASE: v for m, v in limits.items()})


shaper = Shaper()
