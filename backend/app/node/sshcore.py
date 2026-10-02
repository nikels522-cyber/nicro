"""SSH control shared by the panel (main server), cluster node agents and relay agents. Stdlib only:
agents import it from their own directory.

Settings live in /etc/ssh/sshd_config.d/00-vpnpanel.conf (sshd uses the first value it reads, and 00-
sorts before cloud-init's file). Every change is validated with `sshd -t` before it is applied.
Safety: password login can't be disabled while the login user has no key; SSH itself may be turned off
because the panel (through the agent) can always turn it back on.

handle({"action": ...}, user) is the single entry point for remote calls:
  state | enable {on} | password {on} | genkey {name} | delkey {fingerprint}"""
import base64
import hashlib
import pwd
import subprocess
import tempfile
from pathlib import Path

CONF = Path("/etc/ssh/sshd_config.d/00-vpnpanel.conf")
MODE_FILE = Path("/etc/ssh/.vpnpanel-ssh-mode")  # which unit to bring back when SSH is turned on again
KEY_TAG = "vpnpanel:"  # comment prefix of keys generated here


def _run(*cmd: str) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)
    return p.returncode, p.stdout, p.stderr


def _unit_exists(unit: str) -> bool:
    return _run("systemctl", "cat", unit)[0] == 0


def _service() -> str:
    return "ssh" if _unit_exists("ssh.service") else "sshd"


def _is(what: str, unit: str) -> bool:
    return _run("systemctl", what, unit)[1].strip() in ("active", "enabled")


def auth_keys(user: str) -> Path:
    return Path(pwd.getpwnam(user).pw_dir) / ".ssh" / "authorized_keys"


def fingerprint(blob_b64: str) -> str:
    digest = hashlib.sha256(base64.b64decode(blob_b64)).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def list_keys(user: str) -> list[dict]:
    keys = []
    try:
        lines = auth_keys(user).read_text().splitlines()
    except (OSError, KeyError):
        return keys
    for line in lines:
        parts = line.strip().split(None, 2)
        if len(parts) < 2 or line.lstrip().startswith("#"):
            continue
        try:
            fp = fingerprint(parts[1])
        except ValueError:
            continue
        comment = parts[2] if len(parts) > 2 else ""
        keys.append({"type": parts[0], "fingerprint": fp, "name": comment.removeprefix(KEY_TAG),
                     "from_panel": comment.startswith(KEY_TAG)})
    return keys


def state(user: str) -> dict:
    svc = _service()
    _, conf, _ = _run("sshd", "-T")
    opts = dict(line.split(None, 1) for line in conf.splitlines() if " " in line)
    return {
        "enabled": _is("is-active", "ssh.socket") or _is("is-active", f"{svc}.service"),
        "password": opts.get("passwordauthentication", "yes") == "yes",
        "port": int(opts.get("port", "22").split()[0]),
        "user": user,
        "keys": list_keys(user),
    }


def _apply(password: bool, user: str):
    lines = ["# managed by vpnpanel (панель → SSH)",
             f"PasswordAuthentication {'yes' if password else 'no'}",
             "KbdInteractiveAuthentication no",
             "PubkeyAuthentication yes"]
    if user == "root":
        lines.append(f"PermitRootLogin {'yes' if password else 'prohibit-password'}")
    CONF.parent.mkdir(parents=True, exist_ok=True)
    CONF.write_text("\n".join(lines) + "\n")
    code, _, err = _run("sshd", "-t")
    if code != 0:
        CONF.unlink(missing_ok=True)
        raise RuntimeError(f"sshd отклонил настройки: {err.strip()}")
    _run("systemctl", "reload", _service())  # socket-activated sshd reads the config per connection anyway


def set_password(on: bool, user: str):
    if not on and not list_keys(user):
        raise RuntimeError("Сначала создайте SSH-ключ и сохраните его — иначе войти будет нечем")
    _apply(on, user)


def set_enabled(on: bool):
    svc = _service()
    if on:
        mode = MODE_FILE.read_text().strip() if MODE_FILE.exists() else ""
        if not mode:
            mode = "socket" if _unit_exists("ssh.socket") and not _is("is-enabled", f"{svc}.service") else "service"
        unit = "ssh.socket" if mode == "socket" else f"{svc}.service"
        code, _, err = _run("systemctl", "enable", "--now", unit)
        if code != 0:
            raise RuntimeError(f"не удалось включить SSH: {err.strip()}")
    else:  # existing sessions stay alive; the panel can turn SSH back on
        socket = _unit_exists("ssh.socket") and (_is("is-enabled", "ssh.socket") or _is("is-active", "ssh.socket"))
        MODE_FILE.write_text("socket" if socket else "service")
        if _unit_exists("ssh.socket"):
            _run("systemctl", "disable", "--now", "ssh.socket")
        _run("systemctl", "disable", "--now", f"{svc}.service")


def generate_key(name: str, user: str) -> dict:
    """Creates an ed25519 key pair, installs the public key for `user`, returns the private key (not stored)."""
    comment = KEY_TAG + (name.strip() or "admin")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "key"
        code, _, err = _run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(path))
        if code != 0:
            raise RuntimeError(f"ssh-keygen: {err.strip()}")
        private, public = path.read_text(), (Path(d) / "key.pub").read_text().strip()
    pw = pwd.getpwnam(user)
    keys = auth_keys(user)
    if not keys.parent.exists():
        keys.parent.mkdir(mode=0o700)
        _chown(keys.parent, pw)
    with keys.open("a") as f:
        f.write(public + "\n")
    keys.chmod(0o600)
    _chown(keys, pw)
    return {"private_key": private, "public_key": public, "fingerprint": fingerprint(public.split()[1]),
            "user": user}


def _chown(path: Path, pw):
    import os
    try:
        os.chown(path, pw.pw_uid, pw.pw_gid)
    except OSError:
        pass


def delete_key(fp: str, user: str):
    path = auth_keys(user)
    lines = path.read_text().splitlines()
    keep = []
    for line in lines:
        parts = line.strip().split(None, 2)
        try:
            if len(parts) >= 2 and fingerprint(parts[1]) == fp:
                continue
        except ValueError:
            pass
        keep.append(line)
    if len(keep) == len(lines):
        raise RuntimeError("Ключ не найден")
    remaining = [k for k in keep if len(k.split()) >= 2 and not k.lstrip().startswith("#")]
    if not remaining and not state(user)["password"]:
        raise RuntimeError("Это последний ключ, а вход по паролю выключен — сначала включите пароль")
    path.write_text("\n".join(keep) + ("\n" if keep else ""))


def handle(cmd: dict, user: str = "root") -> dict:
    """Remote entry point: returns {"ok": True, "state": ..., [extra]} or {"ok": False, "error": ...}."""
    try:
        action = cmd.get("action", "state")
        extra = {}
        if action == "enable":
            set_enabled(bool(cmd.get("on")))
        elif action == "password":
            set_password(bool(cmd.get("on")), user)
        elif action == "genkey":
            extra["key"] = generate_key(str(cmd.get("name", ""))[:40], user)
        elif action == "delkey":
            delete_key(str(cmd.get("fingerprint", "")), user)
        elif action != "state":
            return {"ok": False, "error": "неизвестное действие"}
        return {"ok": True, "state": state(user), **extra}
    except (RuntimeError, OSError, KeyError) as e:
        return {"ok": False, "error": str(e)}
