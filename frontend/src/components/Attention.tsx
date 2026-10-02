import { useEffect, useState } from 'react'
import { AlertTriangle, Radar, RefreshCw } from 'lucide-react'
import { api, type User } from '../api'
import { bytes, date, relative } from '../format'
import { tr } from '../i18n'

type Exp = User & { reason: 'soon' | 'expired' | 'limited' | 'traffic' }
type Probe = { ts: number; via: string | null; error: string | null; results: { id: string; name: string; ok: boolean; ms: number; error: string }[]
  failed_keys: { key: string; name: string }[]; settings: { enabled: boolean; hide_failed: boolean } }
type Alerts = { active: { key: string; text: string; since: number }[] }

const REASON: Record<Exp['reason'], [string, string]> = {
  soon: [tr("истекает"), 'text-amber-300'], expired: [tr("срок истёк"), 'text-red-300'], limited: [tr("трафик закончился"), 'text-red-300'], traffic: [tr("трафик > 90%"), 'text-amber-300'],
}

export default function Attention({ onOpenUser }: { onOpenUser?: (id: number) => void }) {
  const [exp, setExp] = useState<Exp[]>([])
  const [probe, setProbe] = useState<Probe | null>(null)
  const [alerts, setAlerts] = useState<Alerts | null>(null)
  const [running, setRunning] = useState(false)
  const load = () => {
    api<Exp[]>('/expiring').then(setExp).catch(() => {})
    api<Probe>('/probe').then(setProbe).catch(() => {})
    api<Alerts>('/alerts').then(setAlerts).catch(() => {})
  }
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [])

  async function runProbe() {
    setRunning(true)
    try { setProbe(await api<Probe>('/probe/run', { method: 'POST' })) } finally { setRunning(false) }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {alerts && alerts.active.length > 0 && (
        <section className="card space-y-2 border-red-500/40 xl:col-span-2">
          <div className="flex items-center gap-2 font-medium text-red-300"><AlertTriangle size={18} />{tr("Проблемы сейчас")}</div>
          {alerts.active.map((a) => <div key={a.key} className="text-sm">🔴 {a.text} <span className="text-xs text-muted">· {relative(a.since)}</span></div>)}
        </section>
      )}

      <section className="card space-y-2">
        <div className="flex items-center gap-2 font-medium"><AlertTriangle size={18} className="text-amber-300" />{tr("Требуют внимания")}</div>
        {exp.length === 0 && <div className="text-sm text-muted">{tr("Никто не истекает в ближайшие 7 дней, трафик у всех в порядке.")}</div>}
        <div className="max-h-64 divide-y divide-line/60 overflow-y-auto">
          {exp.map((u) => (
            <button key={u.id} onClick={() => onOpenUser?.(u.id)} className="flex w-full items-center justify-between gap-2 py-1.5 text-left text-sm hover:text-white">
              <span className="font-medium">{u.username}</span>
              <span className="text-xs">
                <span className={REASON[u.reason][1]}>{REASON[u.reason][0]}</span>
                <span className="ml-2 text-muted">{u.expire_at ? date(u.expire_at) : ''}{u.data_limit ? ` · ${bytes(u.used)} / ${bytes(u.data_limit)}` : ''}</span>
              </span>
            </button>
          ))}
        </div>
      </section>

      {probe && (
        <section className="card space-y-2">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 font-medium"><Radar size={18} className="text-accent" />{tr("Проверка из РФ")}{' '}{probe.via && <span className="text-xs font-normal text-muted">{tr("через")}{' '}{probe.via}</span>}</div>
            <button className="btn btn-ghost px-2.5 py-1 text-xs" disabled={running} onClick={runProbe}><RefreshCw size={13} className={running ? 'animate-spin' : ''} />{running ? tr("Проверяю…") : tr("Проверить")}</button>
          </div>
          <div className="text-xs text-muted">
            {probe.ts ? tr("Последняя проверка {0}", relative(probe.ts)) : tr("Ещё не проверялось")}{' '}{tr("· каждые 10 минут.")}
            {probe.settings.hide_failed && tr(" Непрошедшие ключи скрываются из подписок.")}
          </div>
          {probe.error && <div className="text-sm text-red-300">{probe.error}</div>}
          <div className="divide-y divide-line/60">
            {probe.results.map((r) => (
              <div key={r.id} className="flex items-center justify-between gap-2 py-1 text-xs">
                <span className="truncate">{r.ok ? '🟢' : '🔴'} {r.name}</span>
                <span className="shrink-0 text-muted">{r.ok ? tr("{0} мс", r.ms) : tr("не проходит")}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
