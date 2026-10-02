import asyncio
import logging
import uuid as uuidlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from . import config, settings_store
from .api import router
from .cores.devices import access_log, devices
from .cores.hysteria import hy_id
from .cores.manager import manager
from .db import Device, SessionLocal, User, init_db, utcnow
from .links import sub_url, subscription_body, subscription_headers
from . import clientpage, smartlink
from .telegram import invite_link
from .monitor import monitor
from .relays import relay_monitor
from .telegram import bot
from .auth import client_ip
from .firewall import firewall
from . import alerts, backup, billing, cluster, growth, health, l2tp, payments, probe, relays, support
from .audit import AuditMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # request lines would put the bot token into the journal
log = logging.getLogger("vpnpanel")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        firewall.load(settings_store.load(db))
    tasks = [asyncio.create_task(monitor.loop(config.MONITOR_INTERVAL)),
             asyncio.create_task(manager.loop(config.STATS_INTERVAL)),
             asyncio.create_task(relay_monitor.loop()),
             asyncio.create_task(devices.loop(manager.lock)),
             asyncio.create_task(access_log.loop()),
             asyncio.create_task(bot.poll_loop()),
             asyncio.create_task(bot.notify_loop()),
             asyncio.create_task(backup.loop()),
             asyncio.create_task(alerts.loop()),
             asyncio.create_task(probe.loop()),
             asyncio.create_task(monthly_reset_loop()),
             asyncio.create_task(l2tp.loop()),
             asyncio.create_task(payments.check_loop()),
             asyncio.create_task(health.loop()),
             asyncio.create_task(support.staff_bot.loop())]
    yield
    for t in tasks:
        t.cancel()
    await asyncio.to_thread(monitor.flush_daily)
    await manager.collect()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
base = f"/{config.PANEL_PATH}"
app.include_router(router, prefix=f"{base}/api")
app.include_router(cluster.admin, prefix=f"{base}/api")  # panel: manage cluster nodes
app.include_router(cluster.public)  # nodes: /cluster/join, /config, /report (token auth)
app.include_router(billing.router, prefix=f"{base}/api")  # plans, extensions, payments
app.include_router(growth.router, prefix=f"{base}/api")  # promo codes
app.include_router(support.router, prefix=f"{base}/api")  # support conversations
app.include_router(payments.public)  # payment provider webhooks: /pay/webhook/<provider>
app.include_router(relays.public)  # relay agents: /cluster/relay-heartbeat
app.add_middleware(AuditMiddleware, api_prefix=f"{base}/api")


async def monthly_reset_loop():
    """Traffic reset every 30 days for users on monthly plans."""
    while True:
        await asyncio.sleep(3600)
        try:
            if billing.monthly_resets():
                await manager.sync()
        except Exception:
            log.exception("monthly traffic reset failed")


@app.middleware("http")
async def panel_firewall(request: Request, call_next):
    """Panel UI + API only from allowed IPs (firewall.py); subscriptions stay public."""
    path = request.url.path
    if (path == base or path.startswith(base + "/")) and not firewall.check(client_ip(request), path):
        return PlainTextResponse("Not Found", status_code=404)
    return await call_next(request)


@app.get("/sub/{token}")
async def subscription(token: str, request: Request):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.sub_token == token))
    if not u:
        raise HTTPException(404)
    return await serve_subscription(u, request)


@app.get("/c/{code}")
async def smart_link(code: str, request: Request):
    """Smart link: the same subscription behind a short URL; a device-adapted page in browsers."""
    with SessionLocal() as db:
        u = smartlink.resolve(db, code)
    if not u:
        raise HTTPException(404)
    return await serve_subscription(u, request)


async def serve_subscription(u: User, request: Request):
    h = request.headers
    hwid = h.get("x-hwid", "").strip()[:128]
    log.info("subscription fetch: ua=%r hwid=%s headers=%s", h.get("user-agent", ""), bool(hwid),
             sorted(k for k in h.keys() if k.startswith("x-")))
    new_device = False
    with SessionLocal() as db:
        u = db.get(User, u.id)
        device = None
        if hwid:  # the client identifies itself: give this device its own identity
            device = db.scalar(select(Device).where(Device.user_id == u.id, Device.hwid == hwid))
            if device is None:
                device = Device(user_id=u.id, hwid=hwid, uuid=str(uuidlib.uuid4()),
                                ss_key=settings_store.gen_ss_key())
                db.add(device)
                new_device = True
            device.os = h.get("x-device-os", "")[:64]
            device.os_version = h.get("x-ver-os", "")[:64]
            device.model = h.get("x-device-model", "")[:128]
            device.app = h.get("user-agent", "")[:128]
            device.last_sub_at = utcnow()
            db.commit()
        s = settings_store.load(db)
        if not hwid and (request.query_params.get("page") or clientpage.is_browser(h.get("user-agent", ""))):
            link = smartlink.url(u, s)  # opened in a browser: page adapted to the device
            return _with_lang_cookie(HTMLResponse(clientpage.render(
                u, link, smartlink.device_of(h.get("user-agent", "")), invite_link(u), clientpage.extras(u, s),
                page_lang(request))), request)
        active = u.status() == "active" and (device is None or device.enabled)
        body = subscription_body(u, s, device) if active else ""
        headers = subscription_headers(u, s)
    if new_device:
        await manager.sync()  # the client connects right after fetching: its identity must be live
    return PlainTextResponse(body, headers=headers)


def page_lang(request: Request) -> str:
    """Client pages: ?lang= (remembered in a cookie), then the cookie, then the browser language."""
    from .i18n import LANGS, from_accept
    q = request.query_params.get("lang", "")
    if q in LANGS:
        return q
    c = request.cookies.get("nlang", "")
    return c if c in LANGS else from_accept(request.headers.get("accept-language", ""))


def _with_lang_cookie(resp, request: Request):
    from .i18n import LANGS
    q = request.query_params.get("lang", "")
    if q in LANGS:
        resp.set_cookie("nlang", q, max_age=365 * 86400, samesite="lax")
    return resp


@app.get("/status")
def status_page(request: Request):
    """Public server status (Дополнения → Страница статуса)."""
    with SessionLocal() as db:
        if not settings_store.ext(settings_store.load(db), "status")["enabled"]:
            raise HTTPException(404)
    return _with_lang_cookie(HTMLResponse(health.render_status(page_lang(request))), request)


def _client(code: str) -> User:
    with SessionLocal() as db:
        u = smartlink.resolve(db, code)
    if not u:
        raise HTTPException(404)
    return u


@app.post("/c/{code}/order")
async def client_order(code: str, request: Request):
    """Client page: pay for a plan."""
    from .i18n import t
    u = _client(code)
    data = await request.json()
    L = page_lang(request)
    try:
        return await payments.create_order(u.id, int(data.get("plan_id", 0)), str(data.get("provider", "")), lang=L)
    except (RuntimeError, ValueError) as e:
        return JSONResponse({"error": t(L, str(e))}, status_code=400)


@app.post("/c/{code}/paid/{pid}")
async def client_manual_paid(code: str, pid: int, request: Request):
    from .db import Payment
    from .botflows import notify_manual
    from .i18n import t
    u = _client(code)
    with SessionLocal() as db:
        p = db.get(Payment, pid)
        if not p or p.user_id != u.id or p.status != "pending" or p.provider != "manual":
            return JSONResponse({"error": t(page_lang(request), "Этот заказ уже обработан.")}, status_code=400)
    await notify_manual(pid)
    return {"ok": True}


@app.post("/c/{code}/promo")
async def client_promo(code: str, request: Request):
    from .i18n import t
    u = _client(code)
    data = await request.json()
    L = page_lang(request)
    try:
        msg = growth.redeem(u.id, str(data.get("code", ""))[:32], L)
    except ValueError as e:
        return JSONResponse({"error": t(L, str(e))}, status_code=400)
    await manager.sync()
    return {"message": msg}


@app.post("/internal/hy-auth/{secret}")
async def hy_auth(secret: str, request: Request):
    """Hysteria2 HTTP auth hook: {"addr","auth","tx"} -> {"ok","id"}."""
    if secret != config.INTERNAL_SECRET:
        raise HTTPException(404)
    data = await request.json()
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.hy_password == str(data.get("auth", ""))))
        if u and u.status() == "active":
            return JSONResponse({"ok": True, "id": hy_id(u.username, u.hy_password)})
    return JSONResponse({"ok": False, "id": ""})


@app.get(base)
def panel_redirect():
    return RedirectResponse(f"{base}/")


def _panel_url(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}{base}/"


@app.get(f"{base}/nicro.apk")
def android_app():
    """The Android app (WebView wrapper) built by GitHub Actions; installs from any browser."""
    return RedirectResponse(f"https://github.com/{config.REPO}/releases/download/android-latest/nicro.apk")


@app.get(f"{base}/nicro.mobileconfig")
def ios_profile(request: Request):
    """iPhone/iPad: a configuration profile with a full-screen home screen icon for this panel (Web Clip).
    Installs from Safari: Allow → Settings → Profile Downloaded → Install. Behind the panel's secret path."""
    import plistlib
    import uuid as _uuid
    url = _panel_url(request)
    icon = (config.FRONTEND_DIST / "icon-192.png").read_bytes() if (config.FRONTEND_DIST / "icon-192.png").exists() else b""
    clip_id = str(_uuid.uuid5(_uuid.NAMESPACE_URL, url + "#clip")).upper()
    profile_id = str(_uuid.uuid5(_uuid.NAMESPACE_URL, url + "#profile")).upper()
    clip = {"PayloadType": "com.apple.webClip.managed", "PayloadVersion": 1, "PayloadUUID": clip_id,
            "PayloadIdentifier": f"app.nicro.webclip.{clip_id}", "PayloadDisplayName": "nicro",
            "Label": "nicro", "URL": url, "FullScreen": True, "IsRemovable": True, "Precomposed": True}
    if icon:
        clip["Icon"] = icon
    profile = {"PayloadType": "Configuration", "PayloadVersion": 1, "PayloadUUID": profile_id,
               "PayloadIdentifier": f"app.nicro.profile.{profile_id}", "PayloadDisplayName": "nicro",
               "PayloadDescription": "Иконка панели nicro на экране «Домой» / nicro panel icon on the Home Screen",
               "PayloadOrganization": "nicro", "PayloadRemovalDisallowed": False, "PayloadContent": [clip]}
    return Response(plistlib.dumps(profile), media_type="application/x-apple-aspen-config",
                    headers={"Content-Disposition": 'attachment; filename="nicro.mobileconfig"'})


if config.FRONTEND_DIST.exists():
    app.mount(base, StaticFiles(directory=config.FRONTEND_DIST, html=True), name="panel")
