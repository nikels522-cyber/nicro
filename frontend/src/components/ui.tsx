import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'
import type { User } from '../api'
import { tr } from '../i18n'

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 backdrop-blur-sm sm:items-center sm:p-4" onMouseDown={onClose}>
      <div className={`card max-h-[92vh] w-full overflow-y-auto rounded-b-none sm:rounded-2xl ${wide ? 'max-w-3xl' : 'max-w-md'}`}
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button className="rounded-lg p-1 text-muted hover:bg-panel-2 hover:text-white" onClick={onClose}><X size={20} /></button>
        </div>
        {children}
      </div>
    </div>
  )
}

const STATUS: Record<User['status'], [string, string]> = {
  active: [tr("Активен"), 'bg-emerald-500/15 text-emerald-300'],
  disabled: [tr("Отключён"), 'bg-zinc-500/20 text-zinc-300'],
  expired: [tr("Истёк"), 'bg-amber-500/15 text-amber-300'],
  limited: [tr("Лимит"), 'bg-red-500/15 text-red-300'],
}

export function StatusBadge({ status, online }: { status: User['status']; online?: boolean }) {
  const [label, cls] = STATUS[status]
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {online && <span className="size-1.5 animate-pulse rounded-full bg-emerald-400" />}
      {label}
    </span>
  )
}

export function Progress({ value, max }: { value: number; max: number }) {
  const pct = max ? Math.min((value / max) * 100, 100) : 0
  const color = pct > 90 ? 'bg-red-400' : pct > 70 ? 'bg-amber-400' : 'bg-accent'
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-line">
      <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${max ? pct : 0}%` }} />
    </div>
  )
}

export function Stat({ icon, label, value, sub }: { icon: ReactNode; label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card flex items-start gap-4">
      <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-panel-2 text-accent">{icon}</div>
      <div className="min-w-0">
        <div className="text-xs text-muted">{label}</div>
        <div className="mt-0.5 text-xl font-semibold tabular-nums">{value}</div>
        {sub && <div className="mt-0.5 truncate text-xs text-muted">{sub}</div>}
      </div>
    </div>
  )
}

export function Gauge({ value, label, sub }: { value: number; label: string; sub: string }) {
  const r = 38, c = 2 * Math.PI * r
  const color = value > 90 ? '#f87171' : value > 70 ? '#fbbf24' : '#7c6cff'
  return (
    <div className="card flex items-center gap-4">
      <svg viewBox="0 0 100 100" className="size-24 shrink-0 -rotate-90">
        <circle cx="50" cy="50" r={r} fill="none" stroke="#232d42" strokeWidth="9" />
        <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="9" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(value, 100) / 100)} style={{ transition: 'stroke-dashoffset .6s' }} />
        <text x="50" y="50" transform="rotate(90 50 50)" textAnchor="middle" dominantBaseline="central" fill="#e6e9ef" fontSize="20" fontWeight="600">
          {Math.round(value)}%
        </text>
      </svg>
      <div>
        <div className="font-medium">{label}</div>
        <div className="text-sm text-muted">{sub}</div>
      </div>
    </div>
  )
}
