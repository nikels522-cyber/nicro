"""Client page (smart link): what a client sees when opening their link in a browser — status,
traffic, expiry, and an install/import flow adapted to their device, QR for another device and a
button that binds their Telegram to the bot."""
import html
import io
from datetime import timezone

import qrcode
import qrcode.image.svg

from .db import User, utcnow
from .i18n import FLAGS, LANGS, t

GB = 1024 ** 3
CLIENT_UA = ("happ", "v2raytun", "hiddify", "streisand", "nekobox", "nekoray", "v2rayn", "v2rayng", "shadowrocket",
             "clash", "mihomo", "sing-box", "singbox", "v2box", "karing", "foxray", "throne", "stash", "loon")

# app -> (deep link template, {device: store link})
APPS = {
    "Happ": ("happ://add/{url}", {"android": "https://play.google.com/store/apps/details?id=com.happproxy",
                                  "ios": "https://apps.apple.com/app/happ-proxy-utility/id6504287215",
                                  "windows": "https://github.com/Happ-proxy/happ-desktop/releases/latest",
                                  "mac": "https://apps.apple.com/app/happ-proxy-utility/id6504287215"}),
    "v2RayTun": ("v2raytun://import/{url}", {"android": "https://play.google.com/store/apps/details?id=com.v2raytun.android",
                                             "ios": "https://apps.apple.com/app/v2raytun/id6476628951"}),
    "Hiddify": ("hiddify://import/{url}#nicro", {"android": "https://github.com/hiddify/hiddify-app/releases/latest",
                                                "windows": "https://github.com/hiddify/hiddify-app/releases/latest",
                                                "mac": "https://github.com/hiddify/hiddify-app/releases/latest",
                                                "linux": "https://github.com/hiddify/hiddify-app/releases/latest"}),
    "Streisand": ("streisand://import/{url}", {"ios": "https://apps.apple.com/app/streisand/id6450534064"}),
}
RECOMMENDED = {"android": ["Happ", "v2RayTun", "Hiddify"], "ios": ["Happ", "v2RayTun", "Streisand"],
               "windows": ["Hiddify", "Happ"], "mac": ["Happ", "Hiddify"], "linux": ["Hiddify"],
               "other": ["Happ", "v2RayTun", "Hiddify"]}
DEVICE_NAME = {"android": "Android", "ios": "iPhone / iPad", "windows": "Windows", "mac": "Mac", "linux": "Linux",
               "other": "ваше устройство"}


def is_browser(user_agent: str) -> bool:
    ua = user_agent.lower()
    return "mozilla" in ua and not any(c in ua for c in CLIENT_UA)


def _qr_svg(data: str) -> str:
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode().split("?>", 1)[-1]


def extras(u: User, s: dict) -> dict:
    """Optional blocks of the client page: purchase, promo code, referral link, status page."""
    from sqlalchemy import select
    from . import growth, payments, settings_store, smartlink
    from .db import Plan, SessionLocal
    ext = lambda n: settings_store.ext(s, n)  # noqa: E731
    provs = payments.enabled() if not u.parent_id else []
    with SessionLocal() as db:
        plans = list(db.scalars(select(Plan).where(Plan.active, Plan.price > 0).order_by(Plan.sort, Plan.id))) if provs else []
        ref = growth.referral_stats(db, u) if ext("referral")["enabled"] else None
    return {
        "code": smartlink.code(u),
        "plans": [{"id": p.id, "name": p.name, "days": p.days, "gb": p.data_limit_gb, "family": p.family_size,
                   "price": payments.price_for(u, p)[0], "base": p.price} for p in plans],
        "providers": [{"name": p.name, "title": p.title} for p in provs],
        "promo": ext("promo")["enabled"] and not u.parent_id,
        "ref": ref["link"] if ref else None,
        "ref_cfg": ext("referral"),
        "status": f"{s['sub_base_url'].rstrip('/')}/status" if ext("status")["enabled"] else None,
    }


def _extras_html(x: dict, L: str) -> str:
    import json
    e = html.escape
    out = ""
    if x.get("plans"):
        cards = "".join(
            f'<button class="plan" data-id="{p["id"]}"><b>{e(p["name"])}</b><span>{t(L, "{days} дн.", days=p["days"] or "∞")} · '
            f'{t(L, "{n} ГБ", n=f"{p["gb"]:g}") if p["gb"] else t(L, "безлимит")}'
            f'{t(L, ", семья до {n}", n=p["family"] + 1) if p["family"] else ""}</span>'
            f'<em>{p["price"]:g} ₽{f" <s>{p["base"]:g}</s>" if p["price"] != p["base"] else ""}</em></button>'
            for p in x["plans"])
        out += (f'<div class="card" id="buy"><h2>{t(L, "Продлить подписку")}</h2><div class="muted">'
                f'{t(L, "Выберите тариф и способ оплаты — доступ продлится автоматически.")}</div>'
                f'<div class="plans">{cards}</div><div id="methods"></div><div id="payres"></div></div>')
    if x.get("promo"):
        out += (f'<div class="card"><h2>{t(L, "Промокод")}</h2><div class="copy"><input id="promo" placeholder="{e(t(L, "Введите код"))}">'
                f'<button id="promobtn">{t(L, "Применить")}</button></div><div id="promores" class="muted"></div></div>')
    if x.get("ref"):
        c = x["ref_cfg"]
        out += (f'<div class="card"><h2>{t(L, "🤝 Пригласите друга")}</h2><div class="muted">'
                f'{t(L, "Друг оплатит подписку — вам +{bonus} дн., ему +{friend} дн. в подарок.", bonus=c["bonus_days"], friend=c["friend_days"])}</div>'
                f'<div class="copy"><input readonly value="{e(x["ref"])}" id="ref">'
                f'<button onclick="share(&#39;ref&#39;)">{t(L, "Поделиться")}</button></div></div>')
    if x.get("status"):
        out += f'<p class="muted" style="text-align:center"><a href="{e(x["status"])}?lang={L}" style="color:#8b8fa8">{t(L, "Состояние серверов")}</a></p>'
    provs = [{"name": p["name"], "title": t(L, p["title"])} for p in x.get("providers", [])]
    words = {k: t(L, v) for k, v in {"err": "Ошибка", "creating": "Создаю счёт…", "method": "Способ оплаты:",
                                      "paid": "✅ Я оплатил", "thanks": "Спасибо! Администратор проверит перевод и продлит доступ."}.items()}
    js = f"""<script>
const C={json.dumps(x["code"])},P={json.dumps(provs, ensure_ascii=False)},W={json.dumps(words, ensure_ascii=False)},LG={json.dumps(L)};let plan=null;
function share(id){{const v=document.getElementById(id).value;if(navigator.share)navigator.share({{url:v}}).catch(()=>{{}});else{{navigator.clipboard.writeText(v)}}}}
async function post(u,b){{const r=await fetch(u+'?lang='+LG,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(b||{{}})}});const d=await r.json();if(!r.ok)throw new Error(d.error||W.err);return d}}
document.querySelectorAll('.plan').forEach(b=>b.onclick=()=>{{plan=+b.dataset.id;document.querySelectorAll('.plan').forEach(x=>x.classList.toggle('sel',x===b));
const m=document.getElementById('methods');m.innerHTML='<div class="muted" style="margin-top:12px">'+W.method+'</div>'+P.map(p=>`<button class="btn method" data-p="${{p.name}}">${{p.title}}</button>`).join('');
m.querySelectorAll('.method').forEach(x=>x.onclick=()=>pay(x.dataset.p,x));if(P.length===1)pay(P[0].name,m.querySelector('.method'))}});
async function pay(p,btn){{const res=document.getElementById('payres');btn.disabled=true;res.textContent=W.creating;
try{{const d=await post(`/c/${{C}}/order`,{{plan_id:plan,provider:p}});if(d.url){{location.href=d.url;return}}
res.innerHTML=`<div class="note">${{d.text.replace(/[<>&]/g,c=>({{'<':'&lt;','>':'&gt;','&':'&amp;'}})[c]).replace(/\\n/g,'<br>')}}</div><button class="btn" id="paidbtn">${{W.paid}}</button>`;
document.getElementById('paidbtn').onclick=async e=>{{e.target.disabled=true;try{{await post(`/c/${{C}}/paid/${{d.payment_id}}`);res.innerHTML='<div class="note">'+W.thanks+'</div>'}}catch(err){{res.textContent=err.message}}}}}}
catch(e){{res.textContent=e.message}}finally{{btn.disabled=false}}}}
const pb=document.getElementById('promobtn');if(pb)pb.onclick=async()=>{{const r=document.getElementById('promores');try{{const d=await post(`/c/${{C}}/promo`,{{code:document.getElementById('promo').value}});r.textContent=d.message;setTimeout(()=>location.reload(),1500)}}catch(e){{r.textContent=e.message}}}};
</script>"""
    return out + js


def _lang_bar(L: str) -> str:
    return ('<div class="langs">' + "".join(
        f'<a href="?lang={k}" class="{"on" if k == L else ""}">{FLAGS[k]} {v}</a>' for k, v in LANGS.items()) + "</div>")


def render(u: User, url: str, device: str = "other", invite: str | None = None, extra: dict | None = None,
           lang: str = "ru") -> str:
    L = lang
    now = utcnow()
    st = u.status(now)
    badge = {"active": (t(L, "Активна"), "ok"), "expired": (t(L, "Срок истёк"), "bad"),
             "limited": (t(L, "Трафик закончился"), "bad"), "disabled": (t(L, "Отключена"), "off")}[st]
    used = u.used / GB
    if u.data_limit:
        limit = u.data_limit / GB
        pct = min(100, used / limit * 100)
        traffic = f"{used:.1f} / " + t(L, "{n} ГБ", n=f"{limit:.0f}")
        left = t(L, "осталось {n} ГБ", n=f"{max(limit - used, 0):.1f}")
    else:
        pct, traffic, left = 0, t(L, "{n} ГБ", n=f"{used:.1f}"), t(L, "без ограничений")
    if u.expire_at:
        days = (u.expire_at - now).days
        expiry = u.expire_at.replace(tzinfo=timezone.utc).astimezone().strftime("%d.%m.%Y")
        exp_left = t(L, "осталось {days} дн.", days=days) if days >= 0 else t(L, "истекла")
    else:
        expiry, exp_left = t(L, "бессрочно"), ""
    e = html.escape
    rec = RECOMMENDED.get(device, RECOMMENDED["other"])
    main, others = rec[0], rec[1:]
    # apps take the subscription address as is (happ://add/https://…); a percent-encoded one made Hiddify
    # fail with "unexpected connection error" and Happ / v2RayTun ignore it
    enc = url

    def app_block(name: str, primary: bool) -> str:
        tpl, stores = APPS[name]
        store = stores.get(device) or next(iter(stores.values()))
        return (f'<div class="app {"primary" if primary else ""}"><div class="app-head"><b>{name}</b>'
                f'{"<span class=tag>" + t(L, "рекомендуем") + "</span>" if primary else ""}</div>'
                f'<div class="row"><a class="btn ghost" href="{e(store)}" target="_blank" rel="noopener">{t(L, "1. Установить")}</a>'
                f'<a class="btn" href="{e(tpl.format(url=enc))}">{t(L, "2. Добавить подписку")}</a></div></div>')

    tg = (f'<a class="btn tg" href="{e(invite)}">{t(L, "🔔 Получать напоминания в Telegram")}</a>' if invite else "")
    dev = t(L, DEVICE_NAME.get(device, "ваше устройство"))
    return f"""<!doctype html><html lang="{L}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex">
<meta name="theme-color" content="#0a0b14"><title>nicro · {e(u.username)}</title>
<style>
:root{{color-scheme:dark;--bg:#0a0b14;--card:#12131f;--line:#23253a;--muted:#8b8fa8;--txt:#eceef6;--a:#7c6cff;--b:#22d3ee}}
*{{box-sizing:border-box}}body{{margin:0;font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--txt);
padding:max(20px,env(safe-area-inset-top)) 16px max(28px,env(safe-area-inset-bottom));
background-image:radial-gradient(40rem 24rem at 50% -8rem,rgba(124,108,255,.25),transparent)}}
main{{max-width:480px;margin:0 auto}}.brand{{display:flex;align-items:center;gap:10px;margin-bottom:18px}}
.logo{{width:38px;height:38px;border-radius:12px;background:linear-gradient(135deg,var(--a),var(--b));display:grid;place-items:center;font-weight:800;color:#0a0b14}}
.brand b{{font-size:20px;letter-spacing:-.02em}}.muted{{color:var(--muted);font-size:14px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:18px;margin:12px 0}}
.pill{{display:inline-block;padding:3px 11px;border-radius:99px;font-size:13px;font-weight:700}}
.ok{{background:rgba(52,211,153,.15);color:#6ee7b7}}.bad{{background:rgba(248,113,113,.15);color:#fca5a5}}.off{{background:#23253a;color:var(--muted)}}
.stats{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}}.stat{{background:#0e0f1a;border-radius:14px;padding:12px}}
.stat small{{color:var(--muted);display:block;font-size:12px}}.stat b{{font-size:18px}}
.bar{{height:6px;background:#23253a;border-radius:9px;overflow:hidden;margin-top:8px}}.bar i{{display:block;height:100%;width:{pct:.0f}%;background:linear-gradient(90deg,var(--a),var(--b))}}
h2{{font-size:16px;margin:0 0 4px}}.app{{border:1px solid var(--line);border-radius:16px;padding:12px;margin-top:10px}}
.app.primary{{border-color:rgba(124,108,255,.6);background:rgba(124,108,255,.06)}}.app-head{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.tag{{font-size:11px;color:#c4bdff;background:rgba(124,108,255,.18);padding:2px 8px;border-radius:99px}}
.row{{display:grid;grid-template-columns:1fr 1.3fr;gap:8px}}
.btn{{display:block;text-align:center;background:linear-gradient(135deg,var(--a),#6a5cf0);color:#fff;font-weight:600;text-decoration:none;padding:12px 10px;border-radius:13px;font-size:15px;border:0}}
.btn.ghost{{background:#1b1d2e;color:var(--txt);border:1px solid var(--line)}}.btn.tg{{background:#229ed9;margin-top:4px}}
.qr{{background:#fff;border-radius:16px;padding:10px;width:210px;margin:10px auto}}.qr svg{{width:100%;height:auto;display:block}}
.copy{{display:flex;gap:8px;margin-top:10px}}.copy input{{flex:1;min-width:0;background:#0e0f1a;border:1px solid var(--line);color:var(--txt);border-radius:12px;padding:10px;font:12px ui-monospace,monospace}}
.copy button{{background:#1b1d2e;color:var(--txt);border:1px solid var(--line);border-radius:12px;padding:0 14px;font-weight:600}}
.plans{{display:grid;gap:8px;margin-top:10px}}.plan{{display:grid;grid-template-columns:1fr auto;gap:2px 10px;text-align:left;background:#0e0f1a;border:1px solid var(--line);color:var(--txt);border-radius:14px;padding:12px;font:inherit;cursor:pointer}}
.plan span{{grid-column:1;color:var(--muted);font-size:13px}}.plan em{{grid-row:1/3;grid-column:2;align-self:center;font-style:normal;font-weight:800;font-size:17px}}.plan s{{color:var(--muted);font-weight:400;font-size:13px}}
.plan.sel{{border-color:var(--a);background:rgba(124,108,255,.1)}}.method{{width:100%;margin-top:8px}}.note{{background:#0e0f1a;border-radius:12px;padding:12px;margin:10px 0;white-space:normal}}
#payres{{margin-top:8px;color:#c9cce0}}button:disabled{{opacity:.6}}
.langs{{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin:18px 0 4px}}.langs a{{color:var(--muted);text-decoration:none;font-size:13px;padding:4px 9px;border-radius:99px;border:1px solid var(--line)}}.langs a.on{{color:var(--txt);border-color:var(--a)}}
details{{border-top:1px solid var(--line);padding:10px 0}}summary{{cursor:pointer;font-weight:600}}ol{{padding-left:20px;margin:8px 0;color:#c9cce0}}
</style></head><body><main>
<div class="brand"><div class="logo">n</div><div><b>nicro</b><div class="muted">{e(u.username)}</div></div></div>
<div class="card"><span class="pill {badge[1]}">{badge[0]}</span>
<div class="stats"><div class="stat"><small>{t(L, "Трафик")}</small><b>{traffic}</b><div class="muted">{left}</div><div class="bar"><i></i></div></div>
<div class="stat"><small>{t(L, "Подписка")}</small><b>{expiry}</b><div class="muted">{exp_left}</div></div></div>{tg}</div>
<div class="card"><h2>{t(L, "Подключение на {device}", device=dev)}</h2><div class="muted">{t(L, "Установите приложение, затем добавьте подписку в одно нажатие.")}</div>
{app_block(main, True)}{"".join(app_block(n, False) for n in others)}</div>
<div class="card"><h2>{t(L, "На другом устройстве")}</h2><div class="muted">{t(L, "Отсканируйте QR камерой или в приложении — или скопируйте ссылку.")}</div>
<div class="qr">{_qr_svg(url)}</div>
<div class="copy"><input readonly value="{e(url)}" id="u"><button onclick="navigator.clipboard.writeText(document.getElementById('u').value);this.textContent='✓'">{t(L, "Копировать")}</button></div>
<details><summary>{t(L, "Не подключается на мобильном интернете?")}</summary><ol><li>{t(L, "Выберите в приложении сервер с 🛡 и пометкой «мобильный».")}</li><li>{t(L, "Выключите «Частный DNS» (Настройки → Сеть).")}</li><li>{t(L, "Обновите подписку в приложении.")}</li></ol></details>
<details><summary>{t(L, "Ручная настройка")}</summary><ol><li>{t(L, "В приложении нажмите «+» → «Импорт из буфера» / «Добавить подписку».")}</li><li>{t(L, "Вставьте скопированную ссылку.")}</li><li>{t(L, "Выберите сервер и включите VPN.")}</li></ol></details>
</div>{_extras_html(extra, L) if extra else ""}{_lang_bar(L)}</main></body></html>"""
