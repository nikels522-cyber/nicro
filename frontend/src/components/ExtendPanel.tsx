import { useEffect, useState } from 'react'
import { CalendarPlus, History } from 'lucide-react'
import { api, type Plan } from '../api'
import { date } from '../format'
import { tr } from '../i18n'

type Pay = { id: number; plan: string; amount: number; currency: string; provider: string; status: string; comment: string; admin: string; ts: number }

export default function ExtendPanel({ userId, planId, onDone }: { userId: number; planId: number | null; onDone: (msg: string) => void }) {
  const [plans, setPlans] = useState<Plan[]>([])
  const [plan, setPlan] = useState<string>('')
  const [amount, setAmount] = useState('')
  const [pays, setPays] = useState<Pay[]>([])
  const [err, setErr] = useState('')
  const loadPays = () => api<Pay[]>(`/users/${userId}/payments`).then(setPays).catch(() => {})
  useEffect(() => {
    api<Plan[]>('/plans').then((p) => {
      const act = p.filter((x) => x.active)
      setPlans(act)
      const cur = act.find((x) => x.id === planId) ?? act[0]
      if (cur) { setPlan(String(cur.id)); setAmount(String(cur.price)) }
    })
    loadPays()
  }, [userId])

  async function extend(body: object, msg: string) {
    setErr('')
    try { await api(`/users/${userId}/extend`, { body }); await loadPays(); onDone(msg) } catch (e: any) { setErr(e.message) }
  }
  const sel = plans.find((p) => String(p.id) === plan)

  return (
    <div className="space-y-3 rounded-2xl bg-panel-2 p-3">
      <div className="flex items-center gap-2 text-sm font-medium"><CalendarPlus size={16} className="text-accent" />{tr("Продление")}</div>
      <div className="flex flex-wrap gap-2">
        {[7, 30, 90].map((d) => <button key={d} className="btn btn-ghost py-1.5 text-xs" onClick={() => extend({ days: d }, tr("+{0} дней", d))}>+{d}{' '}{tr("дней")}</button>)}
        {[10, 50].map((g) => <button key={g} className="btn btn-ghost py-1.5 text-xs" onClick={() => extend({ add_gb: g }, tr("+{0} ГБ", g))}>+{g}{' '}{tr("ГБ")}</button>)}
      </div>
      {plans.length > 0 && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-44 flex-1">
            <label className="label">{tr("Новый период по тарифу (срок, лимит, трафик с нуля)")}</label>
            <select className="input" value={plan} onChange={(e) => { setPlan(e.target.value); setAmount(String(plans.find((p) => String(p.id) === e.target.value)?.price ?? 0)) }}>
              {plans.map((p) => <option key={p.id} value={p.id}>{p.name} — {p.price} {p.currency}</option>)}
            </select>
          </div>
          <div className="w-28"><label className="label">{tr("Получено,")}{' '}{sel?.currency}</label><input className="input" type="number" min={0} value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
          <button className="btn btn-primary" onClick={() => extend({ plan_id: Number(plan), amount: Number(amount) || 0 }, tr("Продлено: {0}", sel?.name))}>{tr("Продлить")}</button>
        </div>
      )}
      {err && <div className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</div>}
      {pays.length > 0 && (
        <details>
          <summary className="flex cursor-pointer items-center gap-2 text-xs text-muted"><History size={13} />{tr("История продлений и оплат (")}{pays.length})</summary>
          <div className="mt-2 divide-y divide-line/60 text-xs">
            {pays.map((p) => (
              <div key={p.id} className="flex flex-wrap justify-between gap-2 py-1.5">
                <span>{date(p.ts)} · {p.comment || p.plan}</span>
                <span className="text-muted">{p.amount ? `${p.amount} ${p.currency}` : '—'} · {p.provider === 'manual' ? p.admin || tr("вручную") : p.provider}{p.status !== 'paid' && ` · ${p.status}`}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}
