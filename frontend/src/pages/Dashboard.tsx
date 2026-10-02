import { useEffect, useRef, useState } from 'react'
import { Activity, ArrowDownToLine, ArrowUpFromLine, Clock, Network, RotateCw, Users as UsersIcon, Wifi } from 'lucide-react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, wsUrl, type SystemPayload } from '../api'
import { bytes, duration, rate } from '../format'
import { Gauge, Stat } from '../components/ui'
import Attention from '../components/Attention'
import { LOCALE, tr } from '../i18n'

type Point = { ts: number; cpu: number; mem_used: number; net_rx_rate: number; net_tx_rate: number; tcp: number }
type Traffic = { daily: { day: string; up: number; down: number; server_rx: number; server_tx: number }[]; top: { username: string; total: number }[] }

const tooltipStyle = { background: '#121826', border: '1px solid #232d42', borderRadius: 12, fontSize: 12 }
const timeFmt = (ts: number) => new Date(ts * 1000).toLocaleTimeString(LOCALE, { hour: '2-digit', minute: '2-digit' })

const SERVICE_NAMES: Record<string, string> = {
  xray: 'Xray-core', 'hysteria-server': 'Hysteria2', mtg: tr("Telegram-прокси"), caddy: 'Caddy (HTTPS)',
}

export default function Dashboard() {
  const [sys, setSys] = useState<SystemPayload | null>(null)
  const [history, setHistory] = useState<Point[]>([])
  const [traffic, setTraffic] = useState<Traffic | null>(null)
  const [connected, setConnected] = useState(false)
  const lastTs = useRef(0)

  useEffect(() => {
    api<Point[]>('/system/history').then((h) => { setHistory(h); lastTs.current = h.at(-1)?.ts ?? 0 })
    api<Traffic>('/stats/traffic?days=30').then(setTraffic)
    api<SystemPayload>('/system').then(setSys)

    let ws: WebSocket | null = null
    let retry: number | undefined
    let closed = false
    const connect = () => {
      ws = new WebSocket(wsUrl())
      ws.onopen = () => setConnected(true)
      ws.onclose = () => { setConnected(false); if (!closed) retry = window.setTimeout(connect, 3000) }
      ws.onmessage = (e) => {
        const p: SystemPayload = JSON.parse(e.data)
        setSys(p)
        const m = p.metrics
        if (m?.ts && m.ts > lastTs.current) {
          lastTs.current = m.ts
          setHistory((h) => [...h.slice(-449), { ts: m.ts, cpu: m.cpu, mem_used: m.mem_used, net_rx_rate: m.net_rx_rate, net_tx_rate: m.net_tx_rate, tcp: m.tcp }])
        }
      }
    }
    connect()
    return () => { closed = true; clearTimeout(retry); ws?.close() }
  }, [])

  const m = sys?.metrics
  if (!m) return <div className="text-muted">{tr("Загрузка…")}</div>

  async function restart(name: string) {
    await api(`/services/${name}/restart`, { method: 'POST' })
    setSys(await api('/system'))
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{tr("Обзор сервера")}</h1>
          <p className="text-sm text-muted">{tr("Аптайм")}{' '}{duration(m.uptime)} · {m.cpu_count} vCPU · load {m.load.join(' / ')}</p>
        </div>
        <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs ${connected ? 'bg-emerald-500/10 text-emerald-300' : 'bg-zinc-500/15 text-muted'}`}>
          <span className={`size-2 rounded-full ${connected ? 'animate-pulse bg-emerald-400' : 'bg-zinc-500'}`} />
          {connected ? 'Live' : tr("Переподключение…")}
        </span>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Gauge value={m.cpu} label={tr("Процессор")} sub={tr("{0} ядер · load {1}", m.cpu_count, m.load[0])} />
        <Gauge value={(m.mem_used / m.mem_total) * 100} label={tr("Память")} sub={tr("{0} из {1}", bytes(m.mem_used), bytes(m.mem_total))} />
        <Gauge value={(m.disk_used / m.disk_total) * 100} label={tr("Диск")} sub={tr("{0} из {1}", bytes(m.disk_used), bytes(m.disk_total))} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat icon={<UsersIcon size={18} />} label={tr("Пользователи")} value={sys.users.total}
              sub={tr("{0} активных · {1} с ограничением", sys.users.active, sys.users.expired + sys.users.limited)} />
        <Stat icon={<Wifi size={18} />} label={tr("Онлайн")} value={sys.users.online} sub={tr("{0} TCP-соединений", m.tcp)} />
        <Stat icon={<ArrowDownToLine size={18} />} label={tr("Входящий")} value={rate(m.net_rx_rate)} sub={tr("всего {0}", bytes(m.net_rx_total))} />
        <Stat icon={<ArrowUpFromLine size={18} />} label={tr("Исходящий")} value={rate(m.net_tx_rate)} sub={tr("всего {0}", bytes(m.net_tx_total))} />
      </div>

      <Attention onOpenUser={() => { location.hash = '#users' }} />


      <div className="grid gap-4 xl:grid-cols-2">
        <div className="card">
          <div className="mb-4 flex items-center gap-2 font-medium"><Network size={18} className="text-accent" />{tr("Сеть (live)")}</div>
          <ResponsiveContainer height={220}>
            <AreaChart data={history}>
              <defs>
                <linearGradient id="rx" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#7c6cff" stopOpacity={0.4} /><stop offset="1" stopColor="#7c6cff" stopOpacity={0} /></linearGradient>
                <linearGradient id="tx" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#22d3ee" stopOpacity={0.4} /><stop offset="1" stopColor="#22d3ee" stopOpacity={0} /></linearGradient>
              </defs>
              <CartesianGrid stroke="#1b2336" vertical={false} />
              <XAxis dataKey="ts" tickFormatter={timeFmt} stroke="#8a94a8" fontSize={11} minTickGap={40} />
              <YAxis tickFormatter={(v) => rate(v)} stroke="#8a94a8" fontSize={11} width={80} />
              <Tooltip contentStyle={tooltipStyle} labelFormatter={(v) => timeFmt(v as number)} formatter={(v: number, n) => [rate(v), n === 'net_rx_rate' ? tr("Вход") : tr("Выход")]} />
              <Area type="monotone" dataKey="net_rx_rate" stroke="#7c6cff" fill="url(#rx)" strokeWidth={2} isAnimationActive={false} />
              <Area type="monotone" dataKey="net_tx_rate" stroke="#22d3ee" fill="url(#tx)" strokeWidth={2} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <div className="mb-4 flex items-center gap-2 font-medium"><Activity size={18} className="text-accent" />{tr("Нагрузка CPU (live)")}</div>
          <ResponsiveContainer height={220}>
            <AreaChart data={history}>
              <defs><linearGradient id="cpu" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#f59e0b" stopOpacity={0.4} /><stop offset="1" stopColor="#f59e0b" stopOpacity={0} /></linearGradient></defs>
              <CartesianGrid stroke="#1b2336" vertical={false} />
              <XAxis dataKey="ts" tickFormatter={timeFmt} stroke="#8a94a8" fontSize={11} minTickGap={40} />
              <YAxis domain={[0, 100]} unit="%" stroke="#8a94a8" fontSize={11} width={40} />
              <Tooltip contentStyle={tooltipStyle} labelFormatter={(v) => timeFmt(v as number)} formatter={(v: number) => [`${v}%`, 'CPU']} />
              <Area type="monotone" dataKey="cpu" stroke="#f59e0b" fill="url(#cpu)" strokeWidth={2} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {m.cpu_cores.map((c, i) => (
              <div key={i} title={tr("Ядро {0}: {1}%", i, c)} className="h-2 flex-1 min-w-6 overflow-hidden rounded-full bg-line">
                <div className="h-full bg-amber-400 transition-all" style={{ width: `${c}%` }} />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="card xl:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <div className="font-medium">{tr("Трафик пользователей за 30 дней")}</div>
            <div className="text-sm text-muted">{tr("Всего:")}{' '}{bytes(sys.traffic_total)}</div>
          </div>
          <ResponsiveContainer height={240}>
            <BarChart data={traffic?.daily ?? []}>
              <CartesianGrid stroke="#1b2336" vertical={false} />
              <XAxis dataKey="day" tickFormatter={(d) => d.slice(5)} stroke="#8a94a8" fontSize={11} minTickGap={20} />
              <YAxis tickFormatter={(v) => bytes(v, 0)} stroke="#8a94a8" fontSize={11} width={60} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: '#ffffff08' }} formatter={(v: number, n) => [bytes(v), n === 'down' ? tr("Скачано") : tr("Отдано")]} />
              <Bar dataKey="down" stackId="a" fill="#7c6cff" radius={[0, 0, 0, 0]} />
              <Bar dataKey="up" stackId="a" fill="#22d3ee" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="space-y-4">
          <div className="card">
            <div className="mb-3 font-medium">{tr("Сервисы")}</div>
            <div className="space-y-2">
              {Object.entries(sys.services).map(([name, state]) => (
                <div key={name} className="flex items-center justify-between rounded-xl bg-panel-2 px-3 py-2">
                  <div className="flex items-center gap-2 text-sm">
                    <span className={`size-2 rounded-full ${state === 'active' ? 'bg-emerald-400' : 'bg-red-400'}`} />
                    {SERVICE_NAMES[name] ?? name}
                    <span className="text-xs text-muted">{state}</span>
                  </div>
                  <button className="rounded-lg p-1.5 text-muted hover:bg-line hover:text-white" title={tr("Перезапустить")} onClick={() => restart(name)}>
                    <RotateCw size={15} />
                  </button>
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="mb-3 flex items-center gap-2 font-medium"><Clock size={16} className="text-accent" />{tr("Топ за 30 дней")}</div>
            {traffic?.top.length ? (
              <div className="space-y-2">
                {traffic.top.map((t) => (
                  <div key={t.username} className="flex justify-between text-sm">
                    <span className="truncate">{t.username}</span><span className="tabular-nums text-muted">{bytes(t.total)}</span>
                  </div>
                ))}
              </div>
            ) : <div className="text-sm text-muted">{tr("Пока нет данных")}</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
