import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../api'
import { relative } from '../format'
import { tr } from '../i18n'

type Status = {
  installed: boolean; enabled: boolean; strategy: string; result: string; last_check: number; targets: string
  strategies: number; nfqws: boolean; log: string[]; busy: boolean
}

function RelayZapret({ index, name }: { index: number; name: string }) {
  const [st, setSt] = useState<Status | null>(null)
  const [err, setErr] = useState('')
  const [showLog, setShowLog] = useState(false)
  const call = (action: string) => api<Status>(`/relays/${index}/zapret`, { body: { action } })
    .then((r) => { setSt(r); setErr('') }).catch((e) => setErr(e.message))
  useEffect(() => { call('status') }, [])
  useEffect(() => {  // selecting takes a minute or two: follow it
    if (!st?.busy) return
    const t = setInterval(() => call('status'), 4000)
    return () => clearInterval(t)
  }, [st?.busy])

  const state = !st ? tr("загрузка…") : st.busy ? tr("подбираю стратегию…") : !st.enabled ? tr("выключено")
    : st.strategy === 'none' ? tr("не требуется — прямой путь работает") : tr("обход включён")
  return (
    <div className="space-y-2 rounded-2xl bg-panel-2 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{name}</span>
        <span className={`pill ${st?.enabled && st.strategy !== 'none' ? 'bg-emerald-500/15 text-emerald-300' : st?.busy ? 'bg-amber-500/15 text-amber-300' : 'bg-zinc-500/20 text-zinc-300'}`}>{state}</span>
        <span className="flex-1" />
        {st && !st.enabled && <button className="btn btn-primary px-3 py-1.5 text-xs" disabled={st.busy} onClick={() => call('enable')}>{tr("Включить и подобрать")}</button>}
        {st?.enabled && <button className="btn btn-ghost px-3 py-1.5 text-xs" disabled={st.busy} onClick={() => call('select')}><RefreshCw size={13} />{tr("Подобрать заново")}</button>}
        {st?.enabled && <button className="btn btn-ghost px-3 py-1.5 text-xs text-red-300" disabled={st.busy} onClick={() => call('disable')}>{tr("Выключить")}</button>}
      </div>
      {err && <div className="text-xs text-red-300">{err}</div>}
      {st && (
        <div className="space-y-1 text-xs text-muted">
          {st.strategy !== 'none' && <div>{tr("Стратегия:")}{' '}<code className="break-all text-zinc-300">{st.strategy}</code></div>}
          {st.result && <div>{tr("Последняя проверка:")}{' '}{st.result}{st.last_check ? ` · ${relative(st.last_check)}` : ''}</div>}
          <div>{tr("Стратегий в списке:")}{' '}{st.strategies}{' '}{tr("· проверка и обновление списка каждые 6 часов")}</div>
          {st.log.length > 0 && <button className="text-accent" onClick={() => setShowLog(!showLog)}>{showLog ? tr("Скрыть журнал") : tr("Журнал")}</button>}
          {showLog && <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-bg/60 p-2 text-[11px]">{st.log.join('\n')}</pre>}
        </div>
      )}
    </div>
  )
}

/** DPI bypass (zapret / nfqws) on entry points, for their traffic to the main server. */
export function ZapretCard() {
  const [relays, setRelays] = useState<{ name: string; host: string }[] | null>(null)
  useEffect(() => { api<{ relays: { name: string; host: string }[] }>('/settings').then((s) => setRelays(s.relays)).catch(() => setRelays([])) }, [])
  if (relays === null) return <div className="text-sm text-muted">{tr("Загрузка…")}</div>
  if (!relays.length) return <div className="text-sm text-muted">{tr("Нет точек входа — добавьте их на странице «Серверы».")}</div>
  return (
    <div className="space-y-2">
      <div className="rounded-xl bg-panel-2/60 px-3 py-2 text-xs text-muted">
        {tr("Сначала проверяется прямой путь от точки входа до основного сервера. Пока он работает, обход не включается. Если провайдер точки входа начнёт блокировать или резать трафик, точка сама переберёт стратегии и включит первую рабочую. Список стратегий обновляется из репозитория nicro. При сбое трафик идёт как обычно.")}
      </div>
      {relays.map((r, i) => <RelayZapret key={r.host} index={i} name={r.name} />)}
    </div>
  )
}
