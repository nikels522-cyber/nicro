import asyncio
import logging

log = logging.getLogger("vpnpanel.cores")


async def run(*args: str, timeout: float = 20) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "timeout"
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def systemctl(action: str, service: str) -> bool:
    code, _, err = await run("systemctl", action, service)
    if code != 0:
        log.warning("systemctl %s %s failed: %s", action, service, err.strip())
    return code == 0


async def service_states(services: list[str]) -> dict[str, str]:
    _, out, _ = await run("systemctl", "is-active", *services)
    states = out.split()
    return {s: (states[i] if i < len(states) else "unknown") for i, s in enumerate(services)}
