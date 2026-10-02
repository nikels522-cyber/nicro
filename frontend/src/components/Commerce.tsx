import { useEffect, useState } from 'react'
import { Check, Copy, Plus, Trash2 } from 'lucide-react'
import { api, type PaymentsSettings, type Provider } from '../api'
import { Switch } from './brand'
import { LOCALE, tr } from '../i18n'

function CopyField({ value }: { value: string }) {
  const [ok, setOk] = useState(false)
  return (
    <div className="flex gap-2">
      <input className="input font-mono text-xs" readOnly value={value} onFocus={(e) => e.target.select()} />
      <button className="btn btn-ghost px-2.5" onClick={() => navigator.clipboard.writeText(value).then(() => { setOk(true); setTimeout(() => setOk(false), 1200) })}>
        {ok ? <Check size={15} /> : <Copy size={15} />}
      </button>
    </div>
  )
}

function ProviderForm({ p, onSaved }: { p: Provider; onSaved: (s: PaymentsSettings) => void }) {
  const [vals, setVals] = useState<Record<string, string>>(Object.fromEntries(p.fields.map((f) => [f.key, f.value])))
  const [msg, setMsg] = useState('')
  const save = (extra: object = {}) => api<PaymentsSettings>('/payments/settings', { method: 'PUT', body: { providers: { [p.name]: { ...vals, ...extra } } } })
    .then((s) => { onSaved(s); setMsg(tr("Сохранено")) }).catch((e) => setMsg(e.message))
  return (
    <div className={`space-y-2 rounded-2xl border p-3 ${p.enabled ? 'border-accent/40 bg-accent/5' : 'border-line'}`}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 font-medium">{tr(p.title)}
            {p.enabled && p.ready && <span className="pill bg-emerald-500/15 text-emerald-300">{tr("принимает оплату")}</span>}
            {p.enabled && !p.ready && <span className="pill bg-amber-500/15 text-amber-300">{tr("заполните поля")}</span>}
          </div>
          <div className="mt-0.5 text-xs text-muted">{tr(p.hint)}</div>
        </div>
        <Switch on={p.enabled} onChange={(v) => save({ enabled: v })} />
      </div>
      {p.fields.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {p.fields.map((f) => (
            <div key={f.key} className={f.key === 'text' ? 'sm:col-span-2' : ''}>
              <label className="label">{tr(f.label)}</label>
              {f.key === 'text'
                ? <textarea className="input h-20" value={vals[f.key] ?? ''} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })}
                            placeholder={tr("Перевод по СБП на +7 900 000-00-00 (Т-Банк, Иван И.). В комментарии укажите номер заказа.")} />
                : <input className="input font-mono text-xs" type={f.secret ? 'password' : 'text'} value={vals[f.key] ?? ''}
                         placeholder={f.secret && f.value ? tr("сохранено — введите, чтобы заменить") : ''}
                         onFocus={() => f.secret && vals[f.key] === '***' && setVals({ ...vals, [f.key]: '' })}
                         onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} />}
            </div>
          ))}
        </div>
      )}
      {p.webhook && (
        <div><div className="label">{tr("Адрес для уведомлений (вебхук) — вставьте в кабинете платёжки")}</div><CopyField value={p.webhook} /></div>
      )}
      <div className="flex items-center gap-3">
        {p.fields.length > 0 && <button className="btn btn-ghost py-1.5 text-sm" onClick={() => save()}>{tr("Сохранить")}</button>}
        {msg && <span className="text-xs text-muted">{msg}</span>}
      </div>
    </div>
  )
}

type Pending = { id: number; user_id: number; username: string; plan: string; amount: number; provider: string; ts: number }

export function PaymentsCard() {
  const [s, setS] = useState<PaymentsSettings | null>(null)
  const [pending, setPending] = useState<Pending[]>([])
  const [ret, setRet] = useState('')
  const loadPending = () => api<Pending[]>('/payments/pending').then(setPending).catch(() => {})
  useEffect(() => {
    api<{ payments: PaymentsSettings }>('/extensions').then((e) => { setS(e.payments); setRet(e.payments.return_url) })
    loadPending()
  }, [])
  if (!s) return <div className="text-sm text-muted">{tr("Загрузка…")}</div>
  const act = (id: number, what: 'confirm' | 'cancel') => api(`/payments/${id}/${what}`, { body: {} }).then(loadPending).catch((e) => alert(e.message))
  return (
    <div className="space-y-3">
      <div className="rounded-xl bg-panel-2 px-3 py-2 text-xs text-muted">
        {tr("Клиент платит в боте (кнопка «💳 Оплатить») или на своей странице по умной ссылке. После оплаты тариф применяется сам, клиенту и вам приходит сообщение. Панель сама проверяет статус счетов у ЮKassa и CryptoBot — вебхук можно не настраивать. Цены берутся из «Тарифов» (в рублях).")}
      </div>
      {s.providers.map((p) => <ProviderForm key={p.name} p={p} onSaved={setS} />)}
      <div>
        <label className="label">{tr("Куда вернуть клиента после оплаты (необязательно — по умолчанию его страница)")}</label>
        <div className="flex gap-2">
          <input className="input" value={ret} onChange={(e) => setRet(e.target.value)} placeholder={tr("https://t.me/ваш_бот")} />
          <button className="btn btn-ghost" onClick={() => api<PaymentsSettings>('/payments/settings', { method: 'PUT', body: { providers: {}, return_url: ret } }).then(setS)}>{tr("Сохранить")}</button>
        </div>
      </div>
      {pending.length > 0 && (
        <div className="space-y-1.5">
          <div className="label">{tr("Ожидают оплаты")}</div>
          {pending.map((p) => (
            <div key={p.id} className="flex flex-wrap items-center gap-2 rounded-xl bg-panel-2 px-3 py-2 text-sm">
              <span className="font-medium">№{p.id}</span><a className="text-accent" href={`#user/${p.user_id}`}>{p.username}</a>
              <span className="text-muted">{p.plan} · {p.amount} ₽ · {p.provider}</span>
              <span className="flex-1" />
              <button className="btn btn-ghost px-2.5 py-1 text-xs text-emerald-300" onClick={() => act(p.id, 'confirm')}>{tr("Подтвердить")}</button>
              <button className="btn btn-ghost px-2.5 py-1 text-xs text-red-300" onClick={() => act(p.id, 'cancel')}>{tr("Отменить")}</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

type Promo = { id: number; code: string; kind: 'percent' | 'days'; value: number; max_uses: number; used: number; expires_at: number | null; active: boolean; note: string }

export function PromoCard() {
  const [items, setItems] = useState<Promo[]>([])
  const [f, setF] = useState({ code: '', kind: 'percent', value: 10, max_uses: 0, days: 0, note: '' })
  const [msg, setMsg] = useState('')
  const load = () => api<Promo[]>('/promos').then(setItems)
  useEffect(() => { load() }, [])
  const create = () => api('/promos', { body: {
    code: f.code, kind: f.kind, value: Number(f.value), max_uses: Number(f.max_uses), note: f.note,
    expires_at: f.days ? Math.floor(Date.now() / 1000) + Number(f.days) * 86400 : null,
  } }).then(() => { setF({ ...f, code: '' }); setMsg(''); load() }).catch((e) => setMsg(e.message))
  const gen = () => setF({ ...f, code: Math.random().toString(36).slice(2, 8).toUpperCase() })
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-6">
        <div className="sm:col-span-2"><label className="label">{tr("Код")}</label>
          <div className="flex gap-1"><input className="input font-mono uppercase" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} placeholder="SUMMER" />
            <button className="btn btn-ghost px-2" title={tr("Придумать")} onClick={gen}>🎲</button></div></div>
        <div><label className="label">{tr("Тип")}</label><select className="input" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          <option value="percent">{tr("Скидка %")}</option><option value="days">{tr("+ дни")}</option></select></div>
        <div><label className="label">{f.kind === 'percent' ? tr("Скидка, %") : tr("Дней")}</label><input className="input" type="number" value={f.value} onChange={(e) => setF({ ...f, value: +e.target.value })} /></div>
        <div><label className="label">{tr("Лимит (0 = ∞)")}</label><input className="input" type="number" value={f.max_uses} onChange={(e) => setF({ ...f, max_uses: +e.target.value })} /></div>
        <div><label className="label">{tr("Действует, дней")}</label><input className="input" type="number" value={f.days} onChange={(e) => setF({ ...f, days: +e.target.value })} placeholder={tr("0 = всегда")} /></div>
      </div>
      <div className="flex flex-wrap gap-2">
        <input className="input flex-1" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder={tr("заметка: для блогера, для старых клиентов…")} />
        <button className="btn btn-primary" disabled={!f.code.trim()} onClick={create}><Plus size={15} />{tr("Создать")}</button>
      </div>
      {msg && <div className="text-sm text-red-300">{msg}</div>}
      <div className="space-y-1.5">
        {items.map((p) => (
          <div key={p.id} className={`flex flex-wrap items-center gap-2 rounded-xl bg-panel-2 px-3 py-2 text-sm ${p.active ? '' : 'opacity-50'}`}>
            <code className="font-semibold text-accent">{p.code}</code>
            <span>{p.kind === 'percent' ? `−${p.value}%` : tr("+{0} дн.", p.value)}</span>
            <span className="text-xs text-muted">{tr("использован")}{' '}{p.used}{p.max_uses ? tr(" из {0}", p.max_uses) : ''}
              {p.expires_at ? tr(" · до {0}", new Date(p.expires_at * 1000).toLocaleDateString(LOCALE)) : ''}{p.note ? ` · ${p.note}` : ''}</span>
            <span className="flex-1" />
            <Switch on={p.active} onChange={(v) => api(`/promos/${p.id}`, { method: 'PATCH', body: { ...p, active: v } }).then(load)} />
            <button className="btn btn-ghost px-2 py-1 text-red-300" onClick={() => api(`/promos/${p.id}`, { method: 'DELETE' }).then(load)}><Trash2 size={13} /></button>
          </div>
        ))}
        {items.length === 0 && <div className="text-sm text-muted">{tr("Промокодов пока нет. Клиент вводит код в боте (/promo КОД) или на своей странице.")}</div>}
      </div>
    </div>
  )
}
