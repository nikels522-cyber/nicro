"""Direct gRPC client for the Xray stats API.

The panel asks Xray several times a second who is online and from which addresses. Doing that with
`xray api …` starts a 28 MB Go process per question (≈6 per second with a dozen clients online), which made
the CPU graph jump on small servers. Here the same questions go over one persistent gRPC channel; the few
protobuf messages involved are encoded by hand, so no generated stubs are needed.
Rare operations (adding users, routing rules) still use the CLI in xray.py."""
import logging
import os

# the panel starts helper processes (ss, systemctl): keep gRPC from logging a line about it every time
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "false")
import grpc  # noqa: E402

from .. import config

log = logging.getLogger("vpnpanel.xrayapi")
SVC = "/xray.app.stats.command.StatsService/"


# ---------------------------------------------------------------- minimal protobuf


def _varint(n: int) -> bytes:
    n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _str(field: int, s: str) -> bytes:
    b = s.encode()
    return _varint(field << 3 | 2) + _varint(len(b)) + b


def _bool(field: int, v: bool) -> bytes:
    return _varint(field << 3) + _varint(1) if v else b""


def _fields(buf: bytes):
    """Yields (field number, value): ints for varints, bytes for length-delimited."""
    i = 0
    while i < len(buf):
        key, i = _read_varint(buf, i)
        field, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _read_varint(buf, i)
        elif wt == 2:
            ln, i = _read_varint(buf, i)
            v, i = buf[i:i + ln], i + ln
        elif wt == 1:
            v, i = int.from_bytes(buf[i:i + 8], "little"), i + 8
        elif wt == 5:
            v, i = int.from_bytes(buf[i:i + 4], "little"), i + 4
        else:
            raise ValueError("bad wire type")
        yield field, v


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    n = shift = 0
    while True:
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7


def _int64(v: int) -> int:
    return v - (1 << 64) if v >= 1 << 63 else v


# ---------------------------------------------------------------- client


class XrayStats:
    def __init__(self, target: str = config.XRAY_API):
        self.target = target
        self._ch: grpc.aio.Channel | None = None

    def _channel(self) -> grpc.aio.Channel:
        if self._ch is None:
            self._ch = grpc.aio.insecure_channel(self.target)
        return self._ch

    async def _call(self, method: str, req: bytes) -> bytes:
        fn = self._channel().unary_unary(SVC + method, request_serializer=lambda b: b, response_deserializer=lambda b: b)
        return await fn(req, timeout=5)

    async def reset(self):
        """Xray restarted: drop the channel (it would reconnect anyway; this makes it immediate)."""
        if self._ch is not None:
            await self._ch.close()
            self._ch = None

    async def online_ips(self, email: str) -> dict[str, int]:
        """{ip: unix time the address was last seen opening a connection} for one identity (empty when offline)."""
        try:
            resp = await self._call("GetStatsOnlineIpList", _str(1, f"user>>>{email}>>>online"))
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:  # Xray's answer for "no open connections"
                return {}
            raise
        out: dict[str, int] = {}
        for f, v in _fields(resp):
            if f == 2:  # map<string, int64> ips: each entry is {1: key, 2: value}
                k = val = None
                for ef, ev in _fields(v):
                    if ef == 1:
                        k = ev.decode()
                    elif ef == 2:
                        val = _int64(ev)
                if k:
                    out[k] = val or 0
        return out

    async def online_users(self) -> set[str]:
        resp = await self._call("GetAllOnlineUsers", b"")
        users = set()
        for f, v in _fields(resp):
            if f == 1:
                name = v.decode()
                # entries look like "user>>>email>>>online"
                users.add(name.split(">>>")[1] if name.startswith("user>>>") else name)
        return users

    async def query(self, pattern: str, reset: bool = False) -> dict[str, int]:
        """{stat name: value} for stats whose name contains `pattern`."""
        resp = await self._call("QueryStats", _str(1, pattern) + _bool(2, reset))
        out = {}
        for f, v in _fields(resp):
            if f == 1:
                name, val = "", 0
                for sf, sv in _fields(v):
                    if sf == 1:
                        name = sv.decode()
                    elif sf == 2:
                        val = _int64(sv)
                out[name] = val
        return out


stats = XrayStats()
