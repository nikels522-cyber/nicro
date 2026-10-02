import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, Plus, Search, Send, Share2, Trash2, Upload } from 'lucide-react'
import { api, API, getToken, type Plan, type User } from '../api'
import { bytes, date, daysLeft, relative } from '../format'
import { Modal, Progress, StatusBadge } from '../components/ui'
import UserDetail, { ConfirmButton } from './UserDetail'
import { tr } from '../i18n'

const plural = (n: number, one: string, few: string, many: string) =>
  n % 10 === 1 && n % 100 !== 11 ? one : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? few : many

const FILTERS = [
  ['all', tr("Все")], ['active', tr("Активные")], ['online', tr("Онлайн")], ['soon', tr("Истекают ≤7 дн")], ['limited', tr("Лимит")], ['expired', tr("Истёкшие")], ['disabled', tr("Отключённые")],
] as const

export default function Users() {
  const [users, setUsers] = useState<User[]>([])
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>('all')
  const [creating, setCreating] = useState(false)
  const [openId, setOpenIdRaw] = useState<number | null>(() => Number(location.hash.match(/^#user\/(\d+)/)?.[1]) || null)
  // the card is addressable (#user/12): links from support, family, payments open it
  const setOpenId = (id: number | null) => { setOpenIdRaw(id); history.replaceState(null, '', id ? `#user/${id}` : '#users') }
  useEffect(() => {
    const onHash = () => { const m = location.hash.match(/^#user\/(\d+)/); if (m) setOpenIdRaw(Number(m[1])) }
    addEventListener('hashchange', onHash)
    return () => removeEventListener('hashchange', onHash)
  }, [])
  const [sort, setSort] = useState<'new' | 'expire' | 'traffic' | 'name'>('new')
  const [sel, setSel] = useState<Set<number>>(new Set())
  const [plans, setPlans] = useState<Plan[]>([])
  const [bulkMsg, setBulkMsg] = useState('')
  useEffect(() => { api<Plan[]>('/plans').then((p) => setPlans(p.filter((x) => x.active))).catch(() => {}) }, [])
  const toggle = (id: number) => { const n = new Set(sel); n.has(id) ? n.delete(id) : n.add(id); setSel(n) }

  async function bulk(body: object, msg: string) {
    const r = await api<{ count: number }>('/users/bulk', { body: { ids: [...sel], ...body } })
    setBulkMsg(`${msg}: ${r.count}`); setSel(new Set()); load(); setTimeout(() => setBulkMsg(''), 3000)
  }
  async function exportCsv() {
    const r = await fetch(`${API}/export/users.csv`, { headers: { Authorization: `Bearer ${getToken()}` } })
    const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = 'nicro-users.csv'; a.click()
  }
  async function importCsv(file: File) {
    const r = await api<{ created: string[]; skipped: string[] }>('/users/import', { body: { csv: await file.text() } })
    setBulkMsg(tr("Импорт: создано {0}{1}", r.created.length, r.skipped.length ? tr(", пропущено {0} ({1})", r.skipped.length, r.skipped.slice(0, 5).join(', ')) : ''))
    load(); setTimeout(() => setBulkMsg(''), 8000)
  }

  const load = useCallback(() => api<User[]>('/users').then(setUsers), [])
  useEffect(() => {
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [load])

  const shown = useMemo(() => {
    const now = Date.now() / 1000
    const list = users.filter((u) =>
      u.username.toLowerCase().includes(q.toLowerCase()) &&
      (filter === 'all' || (filter === 'online' ? u.online || u.devices_online > 0
        : filter === 'soon' ? !!u.expire_at && u.expire_at > now && u.expire_at - now <= 7 * 86400
        : u.status === filter)))
    const key: Record<typeof sort, (u: User) => number | string> = {
      new: (u) => -u.id, expire: (u) => u.expire_at ?? 1e12, traffic: (u) => -u.used, name: (u) => u.username.toLowerCase(),
    }
    return [...list].sort((a, b) => (key[sort](a) < key[sort](b) ? -1 : key[sort](a) > key[sort](b) ? 1 : 0))
  }, [users, q, filter, sort])

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{tr("Пользователи")}</h1>
          <p className="text-sm text-muted">{users.length}{' '}{tr("всего ·")}{' '}{users.filter((u) => u.online).length}{' '}{tr("онлайн")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-ghost" onClick={exportCsv} title={tr("Экспорт в CSV (Excel)")}><Download size={16} />CSV</button>
          <label className="btn btn-ghost" title={tr("Импорт из CSV: username;days;limit_gb;note;tg_id;multi_device")}>
            <Upload size={16} />{tr("Импорт")}<input type="file" accept=".csv,text/csv" hidden onChange={(e) => e.target.files?.[0] && importCsv(e.target.files[0])} />
          </label>
          <button className="btn btn-primary" onClick={() => setCreating(true)}><Plus size={18} />{tr("Создать")}</button>
        </div>
      </header>
      {bulkMsg && <div className="rounded-xl bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">{bulkMsg}</div>}
      {sel.size > 0 && (
        <div className="sticky top-2 z-10 flex flex-wrap items-center gap-2 rounded-2xl border border-accent/40 bg-panel p-3 shadow-lg">
          <span className="text-sm font-medium">{tr("Выбрано:")}{' '}{sel.size}</span>
          {[7, 30].map((d) => <button key={d} className="btn btn-ghost py-1.5 text-xs" onClick={() => bulk({ action: 'extend', days: d }, tr("Продлено +{0} дн.", d))}>+{d}{' '}{tr("дней")}</button>)}
          {plans.length > 0 && (
            <select className="input w-auto py-1.5 text-xs" value="" onChange={(e) => e.target.value && bulk({ action: 'plan', plan_id: Number(e.target.value) }, tr("Применён тариф"))}>
              <option value="">{tr("Применить тариф…")}</option>{plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          )}
          <button className="btn btn-ghost py-1.5 text-xs" onClick={() => bulk({ action: 'reset' }, tr("Трафик сброшен"))}>{tr("Сбросить трафик")}</button>
          <button className="btn btn-ghost py-1.5 text-xs" onClick={() => bulk({ action: 'enable' }, tr("Включены"))}>{tr("Включить")}</button>
          <button className="btn btn-ghost py-1.5 text-xs" onClick={() => bulk({ action: 'disable' }, tr("Отключены"))}>{tr("Отключить")}</button>
          <ConfirmButton className="btn btn-danger py-1.5 text-xs" confirmText={tr("Удалить {0}?", sel.size)} onConfirm={() => bulk({ action: 'delete' }, tr("Удалено"))}>{tr("Удалить")}</ConfirmButton>
          <button className="ml-auto text-xs text-muted hover:text-white" onClick={() => setSel(new Set())}>{tr("Снять выбор")}</button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full sm:w-72">
          <Search size={16} className="absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
          <input className="input pl-9" placeholder={tr("Поиск по имени")} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className="input w-auto" value={sort} onChange={(e) => setSort(e.target.value as any)}>
          <option value="new">{tr("Сначала новые")}</option><option value="expire">{tr("По сроку окончания")}</option>
          <option value="traffic">{tr("По трафику")}</option><option value="name">{tr("По имени")}</option>
        </select>
        <div className="flex flex-wrap gap-1 rounded-xl border border-line bg-panel p-1">
          {FILTERS.map(([id, label]) => (
            <button key={id} onClick={() => setFilter(id)}
                    className={`rounded-lg px-3 py-1 text-sm ${filter === id ? 'bg-panel-2 text-white' : 'text-muted hover:text-white'}`}>{label}</button>
          ))}
        </div>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="text-left text-xs text-muted">
            <tr className="border-b border-line">
              <th className="w-10 pl-4">
                <input type="checkbox" className="size-4 accent-emerald-500" checked={shown.length > 0 && shown.every((u) => sel.has(u.id))}
                       onChange={(e) => setSel(e.target.checked ? new Set(shown.map((u) => u.id)) : new Set())} />
              </th>
              <th className="px-5 py-3 font-medium">{tr("Имя")}</th>
              <th className="px-5 py-3 font-medium">{tr("Статус")}</th>
              <th className="px-5 py-3 font-medium">{tr("Трафик")}</th>
              <th className="px-5 py-3 font-medium">{tr("Срок")}</th>
              <th className="px-5 py-3 font-medium">{tr("Активность")}</th>
              <th className="px-3 py-3" />
            </tr>
          </thead>
          <tbody>
            {shown.map((u) => (
              <tr key={u.id} onClick={() => setOpenId(u.id)} className={`cursor-pointer border-b border-line/60 last:border-0 hover:bg-panel-2 ${sel.has(u.id) ? 'bg-accent/5' : ''}`}>
                <td className="pl-4" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" className="size-4 accent-emerald-500" checked={sel.has(u.id)} onChange={() => toggle(u.id)} />
                </td>
                <td className="px-5 py-3">
                  <div className="flex items-center gap-2 font-medium">
                    {u.username}
                    {u.tg_id && <span title={tr("Уведомления в Telegram включены")} className="text-sky-400"><Send size={12} /></span>}
                    {!u.multi_device && <span className="rounded bg-sky-500/15 px-1.5 py-px text-[10px] font-normal text-sky-300">{tr("лимит 1 устройство")}</span>}
                    {u.parent_id && <span className="rounded bg-violet-500/15 px-1.5 py-px text-[10px] font-normal text-violet-300">{tr("семья")}</span>}
                    {u.speed_mbps > 0 && <span className="rounded bg-cyan-500/15 px-1.5 py-px text-[10px] font-normal text-cyan-300">{u.speed_mbps}{' '}{tr("Мбит/с")}</span>}
                    {u.pending_signup && <span className="rounded bg-amber-500/15 px-1.5 py-px text-[10px] font-normal text-amber-300">{tr("ждёт оплаты")}</span>}
                    {u.devices_online > 0 && (
                      <span className="rounded bg-emerald-500/15 px-1.5 py-px text-[10px] font-normal text-emerald-300"
                            title={tr("Сколько устройств подключено одновременно прямо сейчас")}>
                        📱 {u.devices_online} {plural(u.devices_online, tr("устройство"), tr("устройства"), tr("устройств"))}
                      </span>
                    )}
                  </div>
                  {u.note && <div className="max-w-56 truncate text-xs text-muted">{u.note}</div>}
                </td>
                <td className="px-5 py-3"><StatusBadge status={u.status} online={u.online} /></td>
                <td className="w-64 px-5 py-3">
                  <div className="mb-1.5 flex justify-between text-xs tabular-nums">
                    <span>{bytes(u.used)}</span><span className="text-muted">{u.data_limit ? bytes(u.data_limit) : '∞'}</span>
                  </div>
                  <Progress value={u.used} max={u.data_limit} />
                </td>
                <td className="px-5 py-3">
                  <div>{daysLeft(u.expire_at)}</div>
                  <div className="text-xs text-muted">{u.expire_at ? date(u.expire_at) : tr("бессрочно")}</div>
                </td>
                <td className="px-5 py-3 text-muted">{u.online ? <span className="text-emerald-300">{tr("онлайн")}</span> : relative(u.last_online)}</td>
                <td className="whitespace-nowrap px-3 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                  {u.smart_link && (
                    <button className="btn btn-ghost mr-1.5 px-2.5 py-1.5 text-accent" title={tr("Поделиться ссылкой клиента")}
                            onClick={() => navigator.share ? navigator.share({ title: 'nicro VPN', url: u.smart_link }).catch(() => {})
                              : navigator.clipboard.writeText(u.smart_link!).then(() => setBulkMsg(tr("Ссылка {0} скопирована", u.username)))}>
                      <Share2 size={15} />
                    </button>
                  )}
                  <ConfirmButton className="btn btn-ghost px-2.5 py-1.5 text-red-300" confirmText={tr("Удалить?")}
                                 onConfirm={async () => { await api(`/users/${u.id}`, { method: 'DELETE' }); load() }}>
                    <Trash2 size={15} />
                  </ConfirmButton>
                </td>
              </tr>
            ))}
            {!shown.length && <tr><td colSpan={7} className="px-5 py-12 text-center text-muted">{tr("Нет пользователей")}</td></tr>}
          </tbody>
        </table>
      </div>

      {creating && <CreateUser onClose={() => setCreating(false)} onCreated={(u) => { setCreating(false); load(); setOpenId(u.id) }} />}
      {openId !== null && <UserDetail id={openId} onClose={() => setOpenId(null)} onChanged={load} />}
    </div>
  )
}

const PRESETS = [7, 30, 90, 365]

function CreateUser({ onClose, onCreated }: { onClose: () => void; onCreated: (u: User) => void }) {
  const [username, setUsername] = useState('')
  const [limit, setLimit] = useState('0')
  const [days, setDays] = useState('30')
  const [note, setNote] = useState('')
  const [multi, setMulti] = useState(true)
  const [tgId, setTgId] = useState('')
  const [planList, setPlanList] = useState<Plan[]>([])
  const [planId, setPlanId] = useState('')
  useEffect(() => { api<Plan[]>('/plans').then((p) => setPlanList(p.filter((x) => x.active))).catch(() => {}) }, [])
  const [error, setError] = useState('')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const d = Number(days)
    try {
      const u = await api<User>('/users', {
        body: {
          username: username.trim(), data_limit_gb: Number(limit) || 0, note, multi_device: multi, tg_id: tgId.trim(),
          plan_id: planId ? Number(planId) : null,
          expire_at: d > 0 ? Math.floor(Date.now() / 1000) + d * 86400 : null,
        },
      })
      onCreated(u)
    } catch (err: any) {
      setError(err.message)
    }
  }

  return (
    <Modal title={tr("Новый пользователь")} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="label">{tr("Имя (латиница)")}</label>
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus placeholder="ivan" />
        </div>
        {planList.length > 0 && (
          <div>
            <label className="label">{tr("Тариф (заполнит срок, трафик и устройства)")}</label>
            <select className="input" value={planId} onChange={(e) => setPlanId(e.target.value)}>
              <option value="">{tr("— без тарифа, задать вручную —")}</option>
              {planList.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.price} {p.currency}</option>)}
            </select>
          </div>
        )}
        {!planId && <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">{tr("Лимит трафика, ГБ (0 = ∞)")}</label>
            <input className="input" type="number" min="0" step="any" value={limit} onChange={(e) => setLimit(e.target.value)} />
          </div>
          <div>
            <label className="label">{tr("Срок, дней (0 = ∞)")}</label>
            <input className="input" type="number" min="0" value={days} onChange={(e) => setDays(e.target.value)} />
          </div>
        </div>}
        {!planId && <div className="flex gap-2">
          {PRESETS.map((p) => (
            <button type="button" key={p} onClick={() => setDays(String(p))}
                    className={`rounded-lg border px-2.5 py-1 text-xs ${days === String(p) ? 'border-accent text-accent' : 'border-line text-muted'}`}>{p}{' '}{tr("дн")}</button>
          ))}
        </div>}
        <div>
          <label className="label">{tr("Заметка")}</label>
          <input className="input" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <div>
          <label className="label">{tr("Telegram ID (необязательно — для уведомлений)")}</label>
          <input className="input font-mono" inputMode="numeric" placeholder={tr("клиент получает его у бота по /start")}
                 value={tgId} onChange={(e) => setTgId(e.target.value)} />
        </div>
        <label className="flex cursor-pointer items-center gap-3 rounded-xl bg-panel-2 px-3 py-2.5 text-sm">
          <input type="checkbox" className="size-4 accent-emerald-500" checked={multi} onChange={(e) => setMulti(e.target.checked)} />
          <span>
            <span className="block font-medium">{tr("Мультиаккаунт")}</span>
            <span className="block text-xs text-muted">{multi ? tr("ключ работает на любом числе устройств") : tr("одновременно только 1 устройство")}</span>
          </span>
        </label>
        {error && <div className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-ghost" onClick={onClose}>{tr("Отмена")}</button>
          <button className="btn btn-primary">{tr("Создать")}</button>
        </div>
      </form>
    </Modal>
  )
}
