import { useEffect, useState } from 'react'
import { KeyRound, Plus, Radio, Save, Trash2, Waypoints } from 'lucide-react'
import { api } from '../api'
import { DomainsCard, UpdatesCard } from '../components/SettingsExtra'
import { tr } from '../i18n'

type S = {
  host: string; sub_base_url: string; reality_public: string; short_id: string; reality_sni: string; fingerprint: string
  xhttp_path: string; ss_method: string; hy_obfs: boolean; hy_masquerade: string
  ports: Record<string, number>; protocols: Record<string, boolean>
  relays: { name: string; host: string; domain?: string }[]
  relay_token: string
  steal_domain: string
  panel_domain: string
  main_name: string
  main_country: string
  hide_ip_new: boolean
  regru: { username: string; password: string }
}

const PROTOCOLS = [
  { key: 'steal', name: tr("🛡 VLESS Reality + XHTTP · свой домен"), desc: tr("Маскировка под ваш сайт с настоящим сертификатом на этом же IP. Работает там, где режут чужую маскировку (мобильные операторы). Рекомендуется."), port: 'steal', proto: 'TCP', extra: 'steal_xhttp' },
  { key: 'vless', name: tr("VLESS + Reality + Vision (чужой сайт)"), desc: tr("Маскировка под сторонний сайт (www.apple.com). Нужен для роутеров со старыми ключами; у вашего провайдера напрямую уже блокируется."), port: 'vless', proto: 'TCP' },
  { key: 'xhttp', name: tr("VLESS + XHTTP + Reality (чужой сайт)"), desc: tr("То же, но трафик в виде HTTP-запросов. Только для приложений на Xray."), port: 'xhttp', proto: 'TCP' },
  { key: 'hy', name: 'Hysteria2', desc: tr("QUIC/UDP с обфускацией. Быстрый, но у вас UDP режется и дома, и на мобильном."), port: 'hy', proto: 'UDP' },
  { key: 'ss', name: 'Shadowsocks 2022', desc: tr("Лёгкий, похож на случайный шум. На мобильном у вас блокируется."), port: 'ss', proto: 'TCP/UDP' },
]

const FINGERPRINTS = ['chrome', 'firefox', 'safari', 'ios', 'edge', 'randomized']

export default function Settings() {
  const [s, setS] = useState<S | null>(null)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  useEffect(() => { api<S>('/settings').then(setS) }, [])
  if (!s) return <div className="text-muted">{tr("Загрузка…")}</div>

  const flash = (m: string) => { setMsg(m); setTimeout(() => setMsg(''), 2500) }

  async function save(patch: Partial<S>) {
    setErr('')
    try {
      setS(await api<S>('/settings', { method: 'PATCH', body: patch }))
      flash(tr("Сохранено, ядра перезапущены"))
    } catch (e: any) { setErr(e.message) }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{tr("Настройки")}</h1>
        {msg && <span className="text-sm text-accent">{msg}</span>}
      </header>
      {err && <div className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</div>}

      <section className="card space-y-3">
        <div className="flex items-center gap-2 font-medium"><Radio size={18} className="text-accent" />{tr("Протоколы")}</div>
        <p className="text-sm text-muted">{tr("Включение и выключение применяется сразу: сервер перезапускает ядра, ключи исчезают из подписок. В приложении после этого обновите подписку.")}</p>
        {PROTOCOLS.map((p) => (
          <label key={p.key} className="flex cursor-pointer items-start gap-4 rounded-xl bg-panel-2 p-4">
            <input type="checkbox" className="mt-1 size-4 accent-emerald-500" checked={!!s.protocols[p.key]}
                   onChange={(e) => save({ protocols: { ...s.protocols, [p.key]: e.target.checked } })} />
            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-2 font-medium">
                {p.name}
                <span className="rounded-md bg-line px-1.5 py-0.5 font-mono text-xs text-muted">
                  {p.proto} :{s.ports[p.port]}{p.extra ? `, :${s.ports[p.extra]}` : ''}
                </span>
                <span className={`rounded-md px-1.5 py-0.5 text-xs ${s.protocols[p.key] ? 'bg-emerald-500/15 text-emerald-300' : 'bg-zinc-500/20 text-zinc-400'}`}>
                  {s.protocols[p.key] ? tr("включён") : tr("выключен")}
                </span>
              </div>
              <div className="text-sm text-muted">{p.desc}</div>
            </div>
          </label>
        ))}
      </section>


      <MaskingForm s={s} onSave={save} onRotate={async () => { await api('/settings/rotate-reality', { method: 'POST' }); setS(await api('/settings')); flash(tr("Ключи Reality обновлены — клиентам нужно обновить подписку")) }} />
      <DomainsCard panelDomain={s.panel_domain} subBase={s.sub_base_url} regru={s.regru}
                   onSave={async (p) => { setS(await api<S>('/settings', { method: 'PATCH', body: p })) }} />
      <UpdatesCard />
      <PasswordForm />
    </div>
  )
}

function MaskingForm({ s, onSave, onRotate }: { s: S; onSave: (p: Partial<S>) => void; onRotate: () => void }) {
  const [f, setF] = useState({ host: s.host, sub_base_url: s.sub_base_url, reality_sni: s.reality_sni, fingerprint: s.fingerprint, hy_masquerade: s.hy_masquerade, hy_obfs: s.hy_obfs, steal_domain: s.steal_domain, main_name: s.main_name, main_country: s.main_country, hide_ip_new: s.hide_ip_new })
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.type === 'checkbox' ? (e.target as HTMLInputElement).checked : e.target.value })

  return (
    <section className="card space-y-4">
      <div className="font-medium">{tr("Маскировка и адреса")}</div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3">
          <label className="label">{tr("🛡 Свой домен для маскировки (A-запись → IP этого сервера)")}</label>
          <input className="input font-mono" value={f.steal_domain} onChange={set('steal_domain')} placeholder="nl.example.ru" />
          <div className="mt-1 text-xs text-muted">
            {tr("Включает ключи «свой домен»: маскировка под ваш сайт с настоящим сертификатом на этом же IP. Лучший вариант для мобильных операторов.")}
          </div>
        </div>
        <div><label className="label">{tr("Название главного сервера (видят клиенты)")}</label><input className="input" value={f.main_name} onChange={set('main_name')} placeholder={tr("например Амстердам")} /></div>
        <div><label className="label">{tr("Страна (код из 2 букв, для флага)")}</label><input className="input uppercase" maxLength={2} value={f.main_country} onChange={set('main_country')} placeholder="NL" /></div>
        <label className="flex items-start gap-3 rounded-xl bg-panel-2 px-3 py-2.5 text-sm sm:col-span-2">
          <input type="checkbox" className="mt-0.5 size-4 accent-violet-500" checked={f.hide_ip_new} onChange={set('hide_ip_new')} />
          <span><span className="block font-medium">{tr("Скрывать IP сервера в подписках новых клиентов")}</span>
            <span className="block text-xs text-muted">{tr("В ключах будут домены (свой домен для маскировки и домены точек входа) вместо IP. Старые клиенты не меняются — у них переключатель в карточке.")}</span></span>
        </label>
        <div><label className="label">{tr("Адрес сервера в ссылках")}</label><input className="input" value={f.host} onChange={set('host')} /></div>
        <div><label className="label">{tr("Базовый URL подписок")}</label><input className="input" value={f.sub_base_url} onChange={set('sub_base_url')} /></div>
        <div>
          <label className="label">{tr("Reality SNI — сайт, под который маскируемся")}</label>
          <input className="input" value={f.reality_sni} onChange={set('reality_sni')} placeholder="www.apple.com" />
        </div>
        <div>
          <label className="label">{tr("TLS-отпечаток клиента (uTLS)")}</label>
          <select className="input" value={f.fingerprint} onChange={set('fingerprint')}>
            {FINGERPRINTS.map((x) => <option key={x}>{x}</option>)}
          </select>
        </div>
        <div><label className="label">{tr("Hysteria2 masquerade (сайт для проверяющих)")}</label><input className="input" value={f.hy_masquerade} onChange={set('hy_masquerade')} /></div>
        <label className="flex items-center gap-3 self-end rounded-xl bg-panel-2 px-3 py-2.5 text-sm">
          <input type="checkbox" className="size-4 accent-emerald-500" checked={f.hy_obfs} onChange={set('hy_obfs')} />
          {tr("Обфускация Salamander для Hysteria2")}
        </label>
      </div>
      <div className="rounded-xl bg-panel-2 p-3 font-mono text-xs break-all text-muted">
        Reality public key: {s.reality_public}<br />short id: {s.short_id} · XHTTP path: {s.xhttp_path}
      </div>
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-primary" onClick={() => onSave(f)}><Save size={16} />{tr("Сохранить")}</button>
        <button className="btn btn-ghost" onClick={onRotate}><KeyRound size={16} />{tr("Сменить ключи Reality")}</button>
      </div>
    </section>
  )
}

function PasswordForm() {
  const [old, setOld] = useState('')
  const [nw, setNw] = useState('')
  const [msg, setMsg] = useState('')
  async function submit(e: React.FormEvent) {
    e.preventDefault()
    try {
      await api('/auth/password', { body: { old_password: old, new_password: nw } })
      setMsg(tr("Пароль изменён")); setOld(''); setNw('')
    } catch (err: any) { setMsg(err.message) }
  }
  return (
    <form onSubmit={submit} className="card space-y-4">
      <div className="font-medium">{tr("Пароль администратора")}</div>
      <div className="grid gap-4 sm:grid-cols-2">
        <input className="input" type="password" placeholder={tr("Текущий пароль")} value={old} onChange={(e) => setOld(e.target.value)} />
        <input className="input" type="password" placeholder={tr("Новый пароль (от 8 символов)")} value={nw} onChange={(e) => setNw(e.target.value)} />
      </div>
      <div className="flex items-center gap-3">
        <button className="btn btn-ghost">{tr("Изменить пароль")}</button>
        {msg && <span className="text-sm text-muted">{msg}</span>}
      </div>
    </form>
  )
}
