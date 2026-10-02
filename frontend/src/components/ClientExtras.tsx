import { useEffect, useState } from 'react'
import { Check, Copy, CreditCard, ExternalLink, Plus, QrCode, Share2, Ticket, Unlink, Users } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { api, type Plan, type UserDetail } from '../api'
import { bytes } from '../format'
import { tr } from '../i18n'

/** The client's smart link, first thing in the card: share / copy / QR in one tap (phone-first). */
export function ShareHero({ u }: { u: UserDetail }) {
  const [copied, setCopied] = useState(false)
  const [qr, setQr] = useState(false)
  const text = tr("Подключение к nicro VPN для {0}: откройте ссылку на телефоне — там кнопки установки и добавления.", u.username)
  const share = () => navigator.share
    ? navigator.share({ title: 'nicro VPN', text, url: u.smart_link }).catch(() => {})
    : copy()
  const copy = () => navigator.clipboard.writeText(u.smart_link).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })
  return (
    <div className="rounded-2xl border border-accent/40 bg-gradient-to-br from-accent/15 to-accent-2/5 p-4">
      <div className="mb-1 text-sm font-semibold">{tr("📲 Ссылка для клиента")}</div>
      <div className="mb-3 text-xs text-muted">{tr("Одна ссылка на любое устройство: откроется страница под телефон/компьютер с кнопками установки и подключения; в приложении работает как подписка.")}</div>
      <div className="mb-3 truncate rounded-xl bg-bg/60 px-3 py-2 font-mono text-xs">{u.smart_link}</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <button className="btn btn-primary" onClick={share}><Share2 size={16} />{tr("Поделиться")}</button>
        <button className="btn btn-ghost" onClick={copy}>{copied ? <Check size={16} className="text-accent" /> : <Copy size={16} />}{copied ? tr("Скопировано") : tr("Копировать")}</button>
        <button className="btn btn-ghost" onClick={() => setQr(!qr)}><QrCode size={16} />{tr("QR-код")}</button>
        <a className="btn btn-ghost" href={u.smart_link + '?page=1'} target="_blank" rel="noopener"><ExternalLink size={16} />{tr("Открыть")}</a>
      </div>
      {qr && <div className="mt-3 flex justify-center"><div className="rounded-2xl bg-white p-3"><QRCodeSVG value={u.smart_link} size={200} /></div></div>}
    </div>
  )
}

/** Family: head + members (shared period and traffic limit). */
export function FamilyBlock({ u, reload }: { u: UserDetail; reload: () => void }) {
  const [name, setName] = useState('')
  const [err, setErr] = useState('')
  const f = u.family
  if (f.parent) {
    return (
      <div className="rounded-2xl bg-panel-2 p-3 text-sm">
        <Users size={15} className="mr-1.5 inline text-sky-300" />{tr("Участник семьи")}{' '}<a className="text-accent" href={`#user/${f.parent.id}`}>{f.parent.username}</a>{tr(": срок и лимит трафика — общие с главным аккаунтом.")}
      </div>
    )
  }
  const add = () => api(`/users/${u.id}/family`, { body: { username: name.trim() } })
    .then(() => { setName(''); setErr(''); reload() }).catch((e) => setErr(e.message))
  return (
    <div className="space-y-2 rounded-2xl bg-panel-2 p-3">
      <div className="flex items-center gap-2 text-sm font-medium"><Users size={15} className="text-sky-300" />{tr("Семья")}
        <span className="text-xs font-normal text-muted">{f.members.length}{f.limit ? tr(" из {0}", f.limit) : ''}{' '}{tr("· свои ключи и устройства, общий срок и трафик")}</span></div>
      {f.members.map((m) => (
        <div key={m.id} className="flex items-center gap-2 text-sm">
          <span className={`size-2 rounded-full ${m.online ? 'bg-emerald-400' : 'bg-zinc-600'}`} />
          <a className="text-accent" href={`#user/${m.id}`}>{m.username}</a>
          <span className="text-xs text-muted">{bytes(m.used)}</span>
          <button className="ml-auto text-xs text-muted hover:text-red-300" title={tr("Отвязать (доступ отключится)")}
                  onClick={() => api(`/users/${u.id}/family/${m.id}`, { method: 'DELETE' }).then(reload)}><Unlink size={14} /></button>
        </div>
      ))}
      <div className="flex gap-2">
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={tr("имя участника, например mama")} />
        <button className="btn btn-ghost" disabled={!name.trim()} onClick={add}><Plus size={15} />{tr("Добавить")}</button>
      </div>
      {err && <div className="text-xs text-red-300">{err}</div>}
    </div>
  )
}

/** Payment link, promo code, referral info. */
export function GrowthBlock({ u, reload }: { u: UserDetail; reload: () => void }) {
  const [plans, setPlans] = useState<Plan[]>([])
  const [provs, setProvs] = useState<{ name: string; title: string }[]>([])
  const [plan, setPlan] = useState('')
  const [prov, setProv] = useState('')
  const [link, setLink] = useState('')
  const [code, setCode] = useState('')
  const [msg, setMsg] = useState('')
  useEffect(() => {
    api<Plan[]>('/plans').then((p) => setPlans(p.filter((x) => x.active && x.price > 0))).catch(() => {})
    api<{ payments: { providers: { name: string; title: string; enabled: boolean; ready: boolean }[] } }>('/extensions')
      .then((e) => setProvs(e.payments.providers.filter((p) => p.enabled && p.ready))).catch(() => {})
  }, [])
  const makeLink = () => api<{ url: string; text: string }>(`/users/${u.id}/pay-link`, { body: { plan_id: Number(plan), provider: prov || provs[0]?.name } })
    .then((r) => { setLink(r.url || r.text); setMsg('') }).catch((e) => setMsg(e.message))
  const promo = () => api<{ message: string }>(`/users/${u.id}/promo`, { body: { code } })
    .then((r) => { setMsg(r.message); setCode(''); reload() }).catch((e) => setMsg(e.message))
  const r = u.referral
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {provs.length > 0 && plans.length > 0 && (
        <div className="space-y-2 rounded-2xl bg-panel-2 p-3">
          <div className="flex items-center gap-2 text-sm font-medium"><CreditCard size={15} className="text-lime-300" />{tr("Ссылка на оплату")}</div>
          <div className="flex flex-wrap gap-2">
            <select className="input w-auto flex-1" value={plan} onChange={(e) => setPlan(e.target.value)}>
              <option value="">{tr("тариф…")}</option>{plans.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.price} ₽</option>)}</select>
            {provs.length > 1 && <select className="input w-auto" value={prov} onChange={(e) => setProv(e.target.value)}>
              {provs.map((p) => <option key={p.name} value={p.name}>{tr(p.title).split(' — ')[0]}</option>)}</select>}
            <button className="btn btn-ghost" disabled={!plan} onClick={makeLink}>{tr("Создать")}</button>
          </div>
          {link && <input className="input font-mono text-xs" readOnly value={link} onFocus={(e) => e.target.select()} />}
        </div>
      )}
      <div className="space-y-2 rounded-2xl bg-panel-2 p-3">
        <div className="flex items-center gap-2 text-sm font-medium"><Ticket size={15} className="text-pink-300" />{tr("Промокод и рефералы")}</div>
        {u.promo && <div className="text-xs text-emerald-300">{tr("Ждёт оплаты: скидка")}{' '}{u.promo.value}% ({u.promo.code})</div>}
        <div className="flex gap-2">
          <input className="input font-mono uppercase" value={code} onChange={(e) => setCode(e.target.value)} placeholder={tr("применить код")} />
          <button className="btn btn-ghost" disabled={!code.trim()} onClick={promo}>OK</button>
        </div>
        <div className="text-xs text-muted">
          {r.invited_by && <>{tr("Пришёл по приглашению")}{' '}<a className="text-accent" href={`#user/${r.invited_by.id}`}>{r.invited_by.username}</a>. </>}
          {tr("Пригласил:")}{' '}{r.invited.length}{r.invited.length ? ` (${r.invited.map((x) => x.username + (x.paid ? ' ✓' : '')).join(', ')})` : ''}
        </div>
        {r.link && <input className="input font-mono text-[11px]" readOnly value={r.link} onFocus={(e) => e.target.select()} />}
      </div>
      {msg && <div className="text-sm text-muted md:col-span-2">{msg}</div>}
    </div>
  )
}
