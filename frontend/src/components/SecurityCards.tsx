import { useEffect, useState } from 'react'
import { Bell, DatabaseBackup, Download, History, KeyRound, Plus, Trash2, UserCog, Users as UsersIcon } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { api, API, getToken, ROLE_NAMES, type Me, type Role } from '../api'
import { bytes, relative } from '../format'
import { ConfirmButton } from '../pages/UserDetail'
import { LOCALE, tr } from '../i18n'

type Msg = { ok: boolean; text: string } | null
const Notice = ({ m }: { m: Msg }) => m && <div className={`rounded-xl px-3 py-2 text-sm ${m.ok ? 'bg-emerald-500/10 text-emerald-300' : 'bg-red-500/10 text-red-300'}`}>{m.text}</div>

export function MyAccountCard() {
  const [me, setMe] = useState<Me | null>(null)
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null)
  const [code, setCode] = useState('')
  const [tg, setTg] = useState('')
  const [msg, setMsg] = useState<Msg>(null)
  const load = () => api<Me>('/auth/me').then((m) => { setMe(m); setTg(m.tg_id) })
  useEffect(() => { load() }, [])
  if (!me) return null
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null)
    try { await fn(); setMsg({ ok: true, text: ok }); load() } catch (e: any) { setMsg({ ok: false, text: e.message }) }
  }
  return (
    <section className="card space-y-4">
      <div className="flex items-center gap-2 font-medium"><UserCog size={20} className="text-accent" />{tr("Мой аккаунт ·")}{' '}{me.username} <span className="text-xs font-normal text-muted">{ROLE_NAMES[me.role]}</span></div>
      <div className="rounded-xl bg-panel-2 p-3 space-y-3">
        <div className="text-sm font-medium">{tr("Двухфакторный вход (2FA) —")}{' '}{me.totp_enabled ? <span className="text-emerald-300">{tr("включён")}</span> : <span className="text-amber-300">{tr("выключен")}</span>}</div>
        {!me.totp_enabled && !setup && <button className="btn btn-primary" onClick={() => api<{ secret: string; uri: string }>('/auth/2fa/setup').then(setSetup)}><KeyRound size={16} />{tr("Включить 2FA")}</button>}
        {setup && (
          <div className="flex flex-wrap items-start gap-4">
            <div className="rounded-xl bg-white p-2"><QRCodeSVG value={setup.uri} size={150} /></div>
            <div className="min-w-48 flex-1 space-y-2 text-sm">
              <div>{tr("1. Отсканируйте QR в Google Authenticator, Яндекс Ключ или Authy.")}</div>
              <div className="text-xs text-muted">{tr("Или введите ключ вручную:")}{' '}<code className="break-all text-zinc-300">{setup.secret}</code></div>
              <div>{tr("2. Введите 6-значный код из приложения:")}</div>
              <div className="flex gap-2">
                <input className="input w-36 text-center font-mono tracking-widest" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />
                <button className="btn btn-primary" onClick={() => run(() => api('/auth/2fa/enable', { body: { secret: setup.secret, code } }), tr("2FA включена — при входе будет нужен код")).then(() => setSetup(null))}>{tr("Подтвердить")}</button>
              </div>
            </div>
          </div>
        )}
        {me.totp_enabled && (
          <div className="flex flex-wrap gap-2">
            <input className="input w-36 text-center font-mono" inputMode="numeric" maxLength={6} placeholder={tr("код")} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />
            <button className="btn btn-danger" onClick={() => run(() => api('/auth/2fa/disable', { body: { code } }), tr("2FA выключена"))}>{tr("Выключить 2FA")}</button>
          </div>
        )}
      </div>
      <div>
        <label className="label">{tr("Мой Telegram ID — команды боту")}{me.role === 'owner' ? tr(", оповещения о проблемах и ежедневные бэкапы") : ''}{' '}{tr("(ID пришлёт бот на /start)")}</label>
        <div className="flex gap-2">
          <input className="input w-60 font-mono" inputMode="numeric" value={tg} onChange={(e) => setTg(e.target.value)} placeholder="123456789" />
          <button className="btn btn-ghost" onClick={() => run(() => api('/auth/me', { method: 'PATCH', body: { tg_id: tg.trim() } }), tr("Сохранено. Напишите боту /help"))}>{tr("Сохранить")}</button>
        </div>
      </div>
      <Notice m={msg} />
    </section>
  )
}

type AdminT = { id: number; username: string; role: Role; totp_enabled: boolean; tg_id: string }

export function AdminsCard() {
  const [list, setList] = useState<AdminT[]>([])
  const [f, setF] = useState({ username: '', password: '', role: 'operator' as Role, tg_id: '' })
  const [msg, setMsg] = useState<Msg>(null)
  const load = () => api<AdminT[]>('/admins').then(setList)
  useEffect(() => { load() }, [])
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null)
    try { await fn(); setMsg({ ok: true, text: ok }); load() } catch (e: any) { setMsg({ ok: false, text: e.message }) }
  }
  return (
    <section className="card space-y-4">
      <div className="flex items-center gap-2 font-medium"><UsersIcon size={20} className="text-accent" />{tr("Администраторы")}</div>
      <div className="text-sm text-muted"><b className="text-zinc-300">{tr("Владелец")}</b>{' '}{tr("— всё.")}{' '}<b className="text-zinc-300">{tr("Оператор")}</b>{' '}{tr("— клиенты, устройства, продления (без серверов, настроек и безопасности).")}{' '}<b className="text-zinc-300">{tr("Поддержка")}</b>{' '}{tr("— только обращения клиентов и просмотр клиентов.")}{' '}<b className="text-zinc-300">{tr("Наблюдатель")}</b>{' '}{tr("— только просмотр.")}</div>
      <div className="divide-y divide-line/60">
        {list.map((a) => (
          <div key={a.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
            <span className="min-w-28 font-medium">{a.username}</span>
            <select className="input w-auto py-1 text-xs" value={a.role} onChange={(e) => run(() => api(`/admins/${a.id}`, { method: 'PATCH', body: { ...a, role: e.target.value, password: '' } }), tr("Роль изменена"))}>
              {Object.entries(ROLE_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <span className="text-xs text-muted">{a.totp_enabled ? '🔐 2FA' : tr("без 2FA")}{a.tg_id && ' · ✈ Telegram'}</span>
            <ConfirmButton className="btn btn-ghost ml-auto px-2.5 py-1 text-xs text-red-300" confirmText={tr("Удалить?")} onConfirm={() => run(() => api(`/admins/${a.id}`, { method: 'DELETE' }), tr("Удалён"))}><Trash2 size={13} /></ConfirmButton>
          </div>
        ))}
      </div>
      <div className="grid gap-2 sm:grid-cols-4">
        <input className="input" placeholder={tr("логин")} value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />
        <input className="input" type="password" placeholder={tr("пароль (от 8)")} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        <select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>{Object.entries(ROLE_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <button className="btn btn-primary" onClick={() => run(() => api('/admins', { body: f }), tr("Администратор {0} создан", f.username)).then(() => setF({ username: '', password: '', role: 'operator', tg_id: '' }))}><Plus size={16} />{tr("Добавить")}</button>
      </div>
      <Notice m={msg} />
    </section>
  )
}

type Backups = { settings: { enabled: boolean; hour: number; keep: number; telegram: boolean }; files: { name: string; size: number; ts: number }[] }

export function BackupsCard() {
  const [b, setB] = useState<Backups | null>(null)
  const [msg, setMsg] = useState<Msg>(null)
  const [busy, setBusy] = useState(false)
  const load = () => api<Backups>('/backups').then(setB)
  useEffect(() => { load() }, [])
  if (!b) return null
  const save = (s: Backups['settings']) => api<Backups['settings']>('/backups/settings', { method: 'PUT', body: s }).then((x) => setB({ ...b, settings: x }))
  async function download(name: string) {
    const r = await fetch(`${API}/backups/file/${name}`, { headers: { Authorization: `Bearer ${getToken()}` } })
    const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click()
  }
  async function restore(file: File) {
    const buf = new Uint8Array(await file.arrayBuffer())
    let bin = ''; buf.forEach((x) => { bin += String.fromCharCode(x) })
    try {
      const r = await api<{ message: string }>('/backups/restore', { body: { data_b64: btoa(bin) } })
      setMsg({ ok: true, text: r.message }); setTimeout(() => location.reload(), 12000)
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
  }
  return (
    <section className="card space-y-4">
      <div className="flex items-center gap-2 font-medium"><DatabaseBackup size={20} className="text-accent" />{tr("Бэкапы")}</div>
      <div className="text-sm text-muted">{tr("Архив базы (клиенты, устройства, ключи, настройки) и секретов панели. Хранятся на сервере и отправляются владельцам в Telegram. Внутри ключи сервера — храните в личном чате.")}</div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-emerald-500" checked={b.settings.enabled} onChange={(e) => save({ ...b.settings, enabled: e.target.checked })} />{tr("Ежедневно в")}</label>
        <select className="input w-auto py-1" value={b.settings.hour} onChange={(e) => save({ ...b.settings, hour: Number(e.target.value) })}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}</select>
        <label className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-emerald-500" checked={b.settings.telegram} onChange={(e) => save({ ...b.settings, telegram: e.target.checked })} />{tr("отправлять в Telegram")}</label>
        <span className="text-muted">{tr("хранить")}</span>
        <input className="input w-16 py-1" type="number" min={1} max={60} value={b.settings.keep} onChange={(e) => save({ ...b.settings, keep: Number(e.target.value) })} />
        <span className="text-muted">{tr("копий")}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-primary" disabled={busy} onClick={async () => { setBusy(true); try { const r = await api<{ name: string; sent: number }>('/backups', { method: 'POST' }); setMsg({ ok: true, text: tr("Создан {0}{1}", r.name, r.sent ? tr(", отправлен в Telegram ({0})", r.sent) : '') }); load() } catch (e: any) { setMsg({ ok: false, text: e.message }) } finally { setBusy(false) } }}>{tr("Сделать бэкап сейчас")}</button>
        <label className="btn btn-ghost">{tr("Восстановить из файла…")}<input type="file" accept=".gz" hidden onChange={(e) => e.target.files?.[0] && restore(e.target.files[0])} /></label>
      </div>
      <Notice m={msg} />
      <div className="divide-y divide-line/60 text-sm">
        {b.files.map((f) => (
          <div key={f.name} className="flex items-center justify-between py-1.5">
            <span className="font-mono text-xs">{f.name}</span>
            <span className="flex items-center gap-3 text-xs text-muted">{bytes(f.size)} · {relative(f.ts)}<button className="text-accent" onClick={() => download(f.name)}><Download size={14} /></button></span>
          </div>
        ))}
      </div>
      <div className="text-xs text-muted">{tr("Переезд на новый сервер: установите панель (install.sh), затем")}{' '}<code className="text-zinc-300">{tr("venv/bin/python -m app.cli restore файл.tar.gz --with-env")}</code>{' '}{tr("и перезапустите — всё вернётся с теми же ссылками.")}</div>
    </section>
  )
}

type AlertsT = { settings: { enabled: boolean; cpu: number; mem: number; disk: number }; active: { key: string; text: string; since: number }[] }

export function AlertsCard() {
  const [a, setA] = useState<AlertsT | null>(null)
  useEffect(() => { api<AlertsT>('/alerts').then(setA) }, [])
  if (!a) return null
  const save = (s: AlertsT['settings']) => api<AlertsT['settings']>('/alerts', { method: 'PUT', body: s }).then((x) => setA({ ...a, settings: x }))
  return (
    <section className="card space-y-3">
      <div className="flex items-center gap-2 font-medium"><Bell size={20} className="text-accent" />{tr("Оповещения в Telegram")}</div>
      <div className="text-sm text-muted">{tr("Владельцам с указанным Telegram ID приходит 🔴 при проблеме и 🟢 когда она исправлена: упал сервис, точка входа или сервер кластера, нехватка питания Pi, перегрузка, диск, сертификаты, ключ перестал проходить из РФ, смена IP точки входа.")}</div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-emerald-500" checked={a.settings.enabled} onChange={(e) => save({ ...a.settings, enabled: e.target.checked })} />{tr("Включены")}</label>
        {(['cpu', 'mem', 'disk'] as const).map((k) => (
          <label key={k} className="flex items-center gap-1.5 text-muted">{{ cpu: 'CPU', mem: tr("Память"), disk: tr("Диск") }[k]} ≥
            <input className="input w-16 py-1" type="number" min={50} max={100} value={a.settings[k]} onChange={(e) => save({ ...a.settings, [k]: Number(e.target.value) })} />%
          </label>
        ))}
      </div>
      {a.active.length > 0 && <div className="space-y-1 text-sm">{a.active.map((x) => <div key={x.key}>🔴 {x.text}</div>)}</div>}
    </section>
  )
}

type Audit = { id: number; ts: number; admin: string; action: string; target: string; details: string; ip: string }

export function AuditCard() {
  const [rows, setRows] = useState<Audit[]>([])
  useEffect(() => { api<Audit[]>('/audit').then(setRows) }, [])
  return (
    <section className="card space-y-3">
      <div className="flex items-center gap-2 font-medium"><History size={20} className="text-accent" />{tr("Журнал действий")}</div>
      <div className="max-h-96 divide-y divide-line/60 overflow-y-auto text-sm">
        {rows.length === 0 && <div className="text-muted">{tr("Пока пусто.")}</div>}
        {rows.map((r) => (
          <details key={r.id} className="py-1.5">
            <summary className="flex cursor-pointer flex-wrap justify-between gap-2">
              <span><b>{r.admin}</b> · {r.action} {r.target && !r.target.startsWith('/') && <span className="text-accent">{r.target}</span>}</span>
              <span className="text-xs text-muted">{new Date(r.ts * 1000).toLocaleString(LOCALE)} · {r.ip}</span>
            </summary>
            {r.details && r.details !== '{}' && <pre className="mt-1 whitespace-pre-wrap break-all rounded-lg bg-bg p-2 text-[11px] text-muted">{r.details}</pre>}
          </details>
        ))}
      </div>
    </section>
  )
}
