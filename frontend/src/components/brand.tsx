import { LANG, LANGS, setLang, type Lang } from '../i18n'
import type { ReactNode } from 'react'

export function Logo({ small }: { small?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className={`grid place-items-center rounded-xl bg-gradient-to-br from-accent to-accent-2 font-black text-white shadow-lg shadow-accent/30 ${small ? 'size-8 text-base' : 'size-10 text-lg'}`}>n</div>
      <div>
        <div className={`font-semibold tracking-tight ${small ? 'text-lg' : 'text-xl'}`}>nicro</div>
        {!small && <div className="-mt-0.5 text-[11px] text-muted">VPN control</div>}
      </div>
    </div>
  )
}

export function PageHeader({ title, subtitle, icon, actions }: { title: string; subtitle?: ReactNode; icon?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="flex items-center gap-2.5 text-2xl font-semibold tracking-tight md:text-[28px]">{icon}{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  )
}

export function Switch({ on, onChange, disabled }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button type="button" disabled={disabled} onClick={() => onChange(!on)} aria-pressed={on}
            className={`relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-50 ${on ? 'bg-gradient-to-r from-accent to-accent-2' : 'bg-zinc-700'}`}>
      <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-all ${on ? 'left-5.5' : 'left-0.5'}`} />
    </button>
  )
}

/** Language of the panel (saved in this browser). */
export function LangSwitch({ className = '' }: { className?: string }) {
  return (
    <div className={`flex gap-1 rounded-xl border border-line bg-panel-2/60 p-1 text-xs ${className}`}>
      {(Object.keys(LANGS) as Lang[]).map((l) => (
        <button key={l} onClick={() => l !== LANG && setLang(l)}
                className={`flex-1 rounded-lg px-2 py-1 transition ${l === LANG ? 'bg-accent text-white' : 'text-muted hover:text-white'}`}>
          {LANGS[l]}
        </button>
      ))}
    </div>
  )
}
