import { Cpu, HardDrive, MemoryStick, Thermometer, Waypoints } from 'lucide-react'
import type { RelayStatus } from '../api'
import { bytes, duration, rate, relative } from '../format'
import { Progress } from './ui'
import { tr } from '../i18n'

// Raspberry Pi firmware flags: bit 0 = under-voltage now, bit 16 = under-voltage has occurred
function powerIssue(throttled: string | null | undefined): string | null {
  if (!throttled) return null
  const v = parseInt(throttled, 16)
  if (Number.isNaN(v)) return null
  if (v & 0x1) return tr("Недостаточное питание прямо сейчас — нужен блок питания 5V 3A")
  if (v & 0x10000) return tr("С момента загрузки было недостаточное питание — возможная причина отключений")
  return null
}

function Row({ icon, label, value, pct }: { icon: React.ReactNode; label: string; value: string; pct?: number }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="flex items-center gap-1.5 text-muted">{icon}{label}</span>
        <span className="tabular-nums">{value}</span>
      </div>
      {pct !== undefined && <Progress value={pct} max={100} />}
    </div>
  )
}

export default function RelayCard({ r }: { r: RelayStatus }) {
  const m = r.metrics
  const power = powerIssue(m?.throttled)
  return (
    <div className={`card space-y-4 ${r.online ? '' : 'border-red-500/40'}`}>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-amber-500/15 text-amber-300"><Waypoints size={18} /></div>
          <div>
            <div className="font-medium">{r.name}</div>
            <div className="break-words font-mono text-xs text-muted">{r.host}{m ? ` · ${m.model}` : ''}</div>
          </div>
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs ${r.online ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'}`}>
          <span className={`size-1.5 rounded-full ${r.online ? 'animate-pulse bg-emerald-400' : 'bg-red-400'}`} />
          {r.online ? tr("онлайн · {0} мс", r.rtt_ms) : tr("нет связи")}
        </span>
      </div>

      {!r.online && (
        <div className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {tr("Точка входа не отвечает")}{r.last_seen ? tr(" (последний раз {0})", relative(r.last_seen)) : ''}{tr(". Ключи «через")}{' '}{r.name}{tr("» сейчас не работают — проверьте питание и кабель. Прямые ключи работают.")}
        </div>
      )}
      {power && <div className="rounded-xl bg-amber-500/10 px-3 py-2 text-sm text-amber-300">⚡ {power}</div>}

      {m && (
        <>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded-xl bg-panel-2 p-2">
              <div className="text-xs text-muted">{tr("Соединений")}</div>
              <div className="text-lg font-semibold tabular-nums">{m.connections}</div>
            </div>
            <div className="rounded-xl bg-panel-2 p-2">
              <div className="text-xs text-muted">{tr("↓ Вход")}</div>
              <div className="text-sm font-semibold tabular-nums">{rate(m.net_rx_rate)}</div>
            </div>
            <div className="rounded-xl bg-panel-2 p-2">
              <div className="text-xs text-muted">{tr("↑ Выход")}</div>
              <div className="text-sm font-semibold tabular-nums">{rate(m.net_tx_rate)}</div>
            </div>
          </div>
          <div className="space-y-3">
            <Row icon={<Cpu size={13} />} label={`CPU · load ${m.load[0]}`} value={`${m.cpu}%`} pct={m.cpu} />
            <Row icon={<MemoryStick size={13} />} label={tr("Память")} value={`${bytes(m.mem_used)} / ${bytes(m.mem_total)}`} pct={(m.mem_used / m.mem_total) * 100} />
            <Row icon={<HardDrive size={13} />} label={tr("Диск")} value={`${bytes(m.disk_used)} / ${bytes(m.disk_total)}`} pct={(m.disk_used / m.disk_total) * 100} />
            {m.temp !== null && (
              <Row icon={<Thermometer size={13} />} label={tr("Температура")} value={`${m.temp} °C`} pct={Math.min((m.temp / 85) * 100, 100)} />
            )}
          </div>
          <div className="flex flex-wrap justify-between gap-2 text-xs text-muted">
            <span>{tr("Аптайм")}{' '}{duration(m.uptime)}</span>
            <span>{tr("Всего через точку: ↓")}{' '}{bytes(m.net_rx_total)} · ↑ {bytes(m.net_tx_total)}</span>
          </div>
        </>
      )}
    </div>
  )
}
