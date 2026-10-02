import { useEffect, useState } from 'react'
import { Check, Copy, DoorOpen, Globe2, Landmark, Pencil, Plus, Server, Terminal, Trash2 } from 'lucide-react'
import { api, type RelayStatus, type SystemPayload } from '../api'
import { bytes, duration, rate, relative } from '../format'
import { Modal, Progress } from '../components/ui'
import { PageHeader } from '../components/brand'
import RelayCard from '../components/RelayCard'
import { ConfirmButton } from './UserDetail'
import { SshCard } from './Security'
import { tr } from '../i18n'

type NodeT = {
  id: number; name: string; address: string; domain: string; country: string; flag: string
  ports: { vision: number; xhttp: number }; enabled: boolean; online: boolean; last_seen: number | null
  info: { hostname?: string; agent?: string; xray?: string; online?: number
    metrics?: { cpu: number; cpu_count: number; mem_used: number; mem_total: number; disk_used: number; disk_total: number
      net_rx_rate: number; net_tx_rate: number; uptime: number } }
}
type RelayCfg = { name: string; host: string; domain?: string; machine_id?: string }
type Settings = { host: string; sub_base_url: string; relay_token: string; relay_command: string; relays: RelayCfg[]; main_name: string; main_country: string }
const flagOf = (c: string) => (c?.length === 2 ? String.fromCodePoint(...[...c.toUpperCase()].map((x) => 0x1f1e6 + x.charCodeAt(0) - 65)) : '🌐')

function CopyBtn({ text }: { text: string }) {
  const [ok, setOk] = useState(false)
  return (
    <button className="btn btn-ghost px-2.5" onClick={() => navigator.clipboard.writeText(text).then(() => { setOk(true); setTimeout(() => setOk(false), 1500) })}>
      {ok ? <Check size={15} className="text-accent" /> : <Copy size={15} />}
    </button>
  )
}

function Bars({ m }: { m: { cpu: number; cpu_count?: number; mem_used: number; mem_total: number; disk_used: number; disk_total: number } }) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <div><div className="mb-1 flex justify-between text-xs"><span className="text-muted">CPU{m.cpu_count ? tr(" · {0} ядер", m.cpu_count) : ''}</span><span>{m.cpu}%</span></div><Progress value={m.cpu} max={100} /></div>
      <div><div className="mb-1 flex justify-between text-xs"><span className="text-muted">{tr("Память")}</span><span>{bytes(m.mem_used)} / {bytes(m.mem_total)}</span></div><Progress value={m.mem_used} max={m.mem_total} /></div>
      <div><div className="mb-1 flex justify-between text-xs"><span className="text-muted">{tr("Диск")}</span><span>{bytes(m.disk_used)} / {bytes(m.disk_total)}</span></div><Progress value={m.disk_used} max={m.disk_total} /></div>
    </div>
  )
}

const ROLE_TAG = {
  main: [tr("Основной"), 'bg-accent/20 text-[#c4bdff]'],
  relay: [tr("Точка входа"), 'bg-amber-500/15 text-amber-300'],
  node: [tr("Выход"), 'bg-cyan-500/15 text-cyan-300'],
} as const

function Tag({ kind }: { kind: keyof typeof ROLE_TAG }) {
  return <span className={`pill ${ROLE_TAG[kind][1]}`}>{ROLE_TAG[kind][0]}</span>
}

function AddNode({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [domain, setDomain] = useState('')
  const [res, setRes] = useState<{ command: string } | null>(null)
  const [err, setErr] = useState('')
  return (
    <Modal title={tr("Добавить узел-выход")} onClose={onClose} wide>
      {!res ? (
        <div className="space-y-4">
          <p className="text-sm text-muted">{tr("Чистый VPS (Ubuntu 22.04/24.04, Debian 12). Панель выдаст одноразовую команду: сервер сам установит Xray и сайт-маскировку, подключится к кластеру и появится у клиентов в подписках.")}</p>
          <div><label className="label">{tr("Название (видят клиенты)")}</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={tr("Германия")} autoFocus /></div>
          <div><label className="label">{tr("Свой домен (необязательно, по умолчанию <ip>.sslip.io)")}</label><input className="input font-mono" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="de.example.com" /></div>
          {err && <div className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</div>}
          <div className="flex justify-end gap-2"><button className="btn btn-ghost" onClick={onClose}>{tr("Отмена")}</button>
            <button className="btn btn-primary" onClick={() => api<{ command: string }>('/nodes/join-token', { body: { name, domain } }).then(setRes).catch((e) => setErr(e.message))}>{tr("Получить команду")}</button></div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="text-sm">{tr("Выполните на новом сервере под")}{' '}<b>root</b>:</div>
          <div className="flex gap-2"><textarea readOnly className="input h-24 font-mono text-xs" value={res.command} onFocus={(e) => e.target.select()} /><CopyBtn text={res.command} /></div>
          <div className="rounded-xl bg-amber-500/10 px-3 py-2 text-xs text-amber-300">{tr("Токен одноразовый и действует 1 час.")}</div>
          <div className="flex justify-end"><button className="btn btn-primary" onClick={onClose}>{tr("Готово")}</button></div>
        </div>
      )}
    </Modal>
  )
}

function RelayEditor({ initial, settings, onSave, onClose }: { initial: RelayCfg | null; settings: Settings; onSave: (r: RelayCfg) => Promise<void>; onClose: () => void }) {
  const [r, setR] = useState<RelayCfg>(initial ?? { name: '', host: '', domain: '' })
  const [err, setErr] = useState('')
  const cmd = settings.relay_command
  return (
    <Modal title={initial ? tr("Точка входа {0}", initial.name) : tr("Добавить точку входа")} onClose={onClose} wide>
      <div className="space-y-4">
        <p className="text-sm text-muted">{tr("Машина с российским IP (Raspberry Pi, VPS в РФ): пересылает подключения на основной сервер — помогает на мобильных сетях. Шифрование сквозное.")}</p>
        {!initial && (
          <div className="rounded-2xl border border-accent/40 bg-accent/5 p-3">
            <div className="mb-1 text-sm font-medium">{tr("Выполните на той машине одну команду (Debian, Ubuntu или Raspberry Pi OS):")}</div>
            <div className="flex gap-2"><div className="input break-all font-mono text-xs">{cmd}</div><CopyBtn text={cmd} /></div>
            <div className="mt-2 text-xs text-muted">{tr("Установщик спросит название точки, настроит пересылку и сам зарегистрирует её здесь — вручную ничего добавлять не нужно. Необязательно: --name RU-1, --ssh-allow ваш_IP.")}</div>
          </div>
        )}
        {!initial && <div className="text-xs text-muted">{tr("Или добавьте уже настроенную машину вручную:")}</div>}
        <div className="grid gap-3 sm:grid-cols-3">
          <div><label className="label">{tr("Название")}</label><input className="input" value={r.name} onChange={(e) => setR({ ...r, name: e.target.value })} placeholder="RU-Pi" /></div>
          <div><label className="label">{tr("IP-адрес")}</label><input className="input font-mono" value={r.host} onChange={(e) => setR({ ...r, host: e.target.value })} /></div>
          <div><label className="label">{tr("Свой домен → этот IP")}</label><input className="input font-mono" value={r.domain ?? ''} onChange={(e) => setR({ ...r, domain: e.target.value })} placeholder="ru.example.ru" /></div>
        </div>
        <div>
          <div className="label">{tr("Переустановка / обновление на машине")}</div>
          <div className="flex gap-2"><div className="input break-all font-mono text-xs">{cmd}</div><CopyBtn text={cmd} /></div>
        </div>
        {err && <div className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</div>}
        <div className="flex justify-end gap-2"><button className="btn btn-ghost" onClick={onClose}>{tr("Отмена")}</button>
          <button className="btn btn-primary" onClick={() => onSave(r).then(onClose).catch((e) => setErr(e.message))}>{tr("Сохранить")}</button></div>
      </div>
    </Modal>
  )
}

export default function Servers() {
  const [nodes, setNodes] = useState<NodeT[]>([])
  const [sys, setSys] = useState<SystemPayload | null>(null)
  const [cfg, setCfg] = useState<Settings | null>(null)
  const [addNode, setAddNode] = useState(false)
  const [editRelay, setEditRelay] = useState<{ i: number | null } | null>(null)
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null)
  const [ssh, setSsh] = useState<{ id: string; name: string } | null>(null)  // SSH control of one server
  const sshBtn = (id: string, name: string, small = false) => (
    <button className={`btn btn-ghost ${small ? 'px-3 py-1 text-xs' : 'px-3 py-1.5 text-sm'}`} onClick={() => setSsh({ id, name })}><Terminal size={small ? 13 : 15} />SSH</button>)
  const load = () => { api<NodeT[]>('/nodes').then(setNodes); api<SystemPayload>('/system').then(setSys); api<Settings>('/settings').then(setCfg) }
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t) }, [])

  const saveRelays = async (relays: RelayCfg[]) => { setCfg(await api<Settings>('/settings', { method: 'PATCH', body: { relays } })); load() }
  const patchNode = async (id: number, body: object) => { await api(`/nodes/${id}`, { method: 'PATCH', body }); load() }
  const m = sys?.metrics
  const relayStatus = (host: string): RelayStatus | undefined => sys?.relays?.find((r) => r.host === host)

  return (
    <div className="max-w-5xl">
      <PageHeader title={tr("Серверы")} icon={<Server className="text-accent" />}
                  subtitle={tr("Кластер nicro: основной сервер хранит клиентов и ключи; вспомогательные — точки входа из РФ и узлы-выходы в других странах. Трафик, лимиты и устройства общие.")}
                  actions={<>
                    <button className="btn btn-ghost" onClick={() => setEditRelay({ i: null })}><DoorOpen size={16} />{tr("Точка входа")}</button>
                    <button className="btn btn-primary" onClick={() => setAddNode(true)}><Plus size={16} />{tr("Узел-выход")}</button>
                  </>} />

      {/* level 0: main */}
      {m && (
        <section className="card space-y-3 border-accent/40 bg-gradient-to-br from-accent/10 to-transparent">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-3">
              <div className="grid size-11 place-items-center rounded-2xl bg-accent/20 text-accent"><Landmark size={22} /></div>
              <div>
                <div className="flex items-center gap-2 text-lg font-semibold">{flagOf(cfg?.main_country ?? '')} {cfg?.main_name || tr("Основной сервер")}{' '}<Tag kind="main" /></div>
                <div className="font-mono text-xs text-muted">{cfg?.host}{' '}{tr("· панель, база, подписки")}</div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="pill bg-emerald-500/15 text-emerald-300">{tr("● онлайн ·")}{' '}{duration(m.uptime)}</span>
              {sshBtn('main', cfg?.main_name || tr("Основной сервер"))}
            </div>
          </div>
          <Bars m={m} />
          <div className="text-xs text-muted">↓ {rate(m.net_rx_rate)} · ↑ {rate(m.net_tx_rate)}{' '}{tr("· устройств онлайн")}{' '}{sys?.users.online}</div>
        </section>
      )}

      {/* level 1: auxiliary */}
      <div className="ml-5 border-l-2 border-dashed border-line pl-5 md:ml-8 md:pl-8">
        <div className="relative mt-6 mb-3 flex items-center gap-2 text-sm font-semibold text-amber-300">
          <span className="absolute -left-[1.6rem] top-1/2 h-0.5 w-5 bg-line md:-left-[2.35rem] md:w-8" />
          <DoorOpen size={17} />{tr("Точки входа · вход из РФ")}
        </div>
        {cfg?.relays.length === 0 && <div className="card text-sm text-muted">{tr("Нет. Точка входа с российским IP нужна, если на мобильном интернете режут зарубежные серверы.")}</div>}
        <div className="grid gap-4 lg:grid-cols-2">
          {cfg?.relays.map((r, i) => {
            const st = relayStatus(r.host)
            return (
              <div key={r.host} className="space-y-2">
                {st ? <RelayCard r={st} /> : <div className="card text-sm text-muted">{r.name} · {r.host}{' '}{tr("— ожидаю данные агента…")}</div>}
                <div className="flex flex-wrap items-center gap-2 px-1 text-xs text-muted">
                  <Tag kind="relay" />{r.domain && <span className="font-mono">{r.domain}</span>}
                  <button className="ml-auto flex items-center gap-1 hover:text-white" onClick={() => setSsh({ id: `r${i}`, name: r.name })}><Terminal size={12} />SSH</button>
                  <button className="flex items-center gap-1 hover:text-white" onClick={() => setEditRelay({ i })}><Pencil size={12} />{tr("изменить")}</button>
                  <ConfirmButton className="flex items-center gap-1 text-red-300" confirmText={tr("Удалить из кластера?")}
                                 onConfirm={() => saveRelays(cfg.relays.filter((_, j) => j !== i))}><Trash2 size={12} />{tr("удалить")}</ConfirmButton>
                </div>
              </div>
            )
          })}
        </div>

        <div className="relative mt-8 mb-3 flex items-center gap-2 text-sm font-semibold text-cyan-300">
          <span className="absolute -left-[1.6rem] top-1/2 h-0.5 w-5 bg-line md:-left-[2.35rem] md:w-8" />
          <Globe2 size={17} />{tr("Узлы-выходы · другие страны")}
        </div>
        {nodes.length === 0 && <div className="card text-sm text-muted">{tr("Нет. Добавьте сервер в другой стране — клиенты получат его ключи автоматически.")}</div>}
        <div className="space-y-4">
          {nodes.map((n) => (
            <section key={n.id} className={`card space-y-3 ${!n.online ? 'border-red-500/40' : ''} ${!n.enabled ? 'opacity-60' : ''}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-lg font-medium">
                    <span>{n.flag}</span>
                    {renaming?.id === n.id ? (
                      <input className="input h-8 w-44" autoFocus value={renaming.name} onChange={(e) => setRenaming({ id: n.id, name: e.target.value })}
                             onBlur={() => { patchNode(n.id, { name: renaming.name }); setRenaming(null) }} onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()} />
                    ) : <button onClick={() => setRenaming({ id: n.id, name: n.name })}>{n.name}</button>}
                    <Tag kind="node" />
                  </div>
                  <div className="font-mono text-xs text-muted">{n.address} · {n.domain}</div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`pill ${n.online ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'}`}>
                    {n.online ? tr("● онлайн · устройств {0}", n.info.online ?? 0) : tr("нет связи · {0}", n.last_seen ? relative(n.last_seen) : tr("ещё не подключался"))}
                  </span>
                  {sshBtn(`n${n.id}`, n.name, true)}
                  <button className="btn btn-ghost px-3 py-1 text-xs" onClick={() => patchNode(n.id, { enabled: !n.enabled })}>{n.enabled ? tr("Вывести из подписок") : tr("Вернуть в подписки")}</button>
                  <ConfirmButton className="btn btn-ghost px-2.5 py-1 text-xs text-red-300" confirmText={tr("Удалить?")} onConfirm={async () => { await api(`/nodes/${n.id}`, { method: 'DELETE' }); load() }}><Trash2 size={14} /></ConfirmButton>
                </div>
              </div>
              {n.info.metrics && <Bars m={n.info.metrics} />}
              {n.info.metrics && <div className="text-xs text-muted">↓ {rate(n.info.metrics.net_rx_rate)} · ↑ {rate(n.info.metrics.net_tx_rate)}{' '}{tr("· аптайм")}{' '}{duration(n.info.metrics.uptime)}{n.info.agent && tr(" · агент {0}", n.info.agent)}</div>}
            </section>
          ))}
        </div>
      </div>

      {ssh && <Modal title={`SSH · ${ssh.name}`} onClose={() => setSsh(null)} wide><SshCard initial={ssh.id} bare /></Modal>}
      {addNode && <AddNode onClose={() => { setAddNode(false); load() }} />}
      {editRelay && cfg && (
        <RelayEditor initial={editRelay.i === null ? null : cfg.relays[editRelay.i]} settings={cfg} onClose={() => setEditRelay(null)}
                     onSave={(r) => saveRelays(editRelay.i === null ? [...cfg.relays, r] : cfg.relays.map((x, j) => (j === editRelay.i ? { ...x, ...r } : x)))} />
      )}
    </div>
  )
}
