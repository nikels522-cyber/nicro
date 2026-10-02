import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, CheckCircle2, LifeBuoy, Plus, RotateCcw, Send, Settings2, Trash2, UserCheck } from 'lucide-react'
import { api, ROLE_NAMES, type Role } from '../api'
import { relative } from '../format'
import { PageHeader } from '../components/brand'
import { tr } from '../i18n'

type Status = 'open' | 'answered' | 'closed'
type Thread = { chat_id: string; label: string; user_id: number | null; last: string; last_dir: 'in' | 'out'; ts: number; unread: number; status: Status; assignee: string }
type Conv = { chat_id: string; label: string; user_id: number | null; status: Status; assignee: string; messages: { id: number; dir: 'in' | 'out'; text: string; admin: string; ts: number }[] }
type Tpl = { id: string; title: string; text: string }
type SupportCfg = {
  enabled: boolean; mode: 'panel' | 'bot' | 'staffbot'; staff_bot_token: string; staff_bot: string | null
  roles: Role[]; autoreply: string; templates: Tpl[]; staff: { username: string; role: Role; tg: boolean }[]
}

const STATUS: Record<Status, [string, string]> = {
  open: [tr("новое"), 'bg-amber-500/15 text-amber-300'],
  answered: [tr("отвечено"), 'bg-sky-500/15 text-sky-300'],
  closed: [tr("закрыто"), 'bg-zinc-500/20 text-zinc-400'],
}
const FILTERS = [['active', tr("Активные")], ['open', tr("Новые")], ['closed', tr("Закрытые")], ['', tr("Все")]] as const
const VARS = tr("{name} — имя клиента, {link} — его ссылка, {expire} — дата окончания, {days} — дней осталось, {traffic_left} — остаток трафика")

function SupportSettings({ onClose }: { onClose: () => void }) {
  const [c, setC] = useState<SupportCfg | null>(null)
  const [token, setToken] = useState('')
  const [msg, setMsg] = useState('')
  useEffect(() => { api<SupportCfg>('/support/settings').then((x) => { setC(x); setToken(x.staff_bot_token) }) }, [])
  if (!c) return <div className="card text-sm text-muted">{tr("Загрузка…")}</div>
  const set = (p: Partial<SupportCfg>) => setC({ ...c, ...p })
  const save = () => api<SupportCfg>('/support/settings', { method: 'PUT', body: { ...c, staff_bot_token: token } })
    .then((x) => { setC(x); setToken(x.staff_bot_token); setMsg(tr("Сохранено")) }).catch((e) => setMsg(e.message))
  const modes = [
    ['panel', tr("Только в панели"), tr("Обращения видны на этой странице, в Telegram никому не пересылаются.")],
    ['bot', tr("Основной бот → персоналу"), tr("Клиентский бот пересылает обращения сотрудникам с Telegram ID; отвечают через «Ответить» или кнопки шаблонов.")],
    ['staffbot', tr("Отдельный бот поддержки"), tr("Отдельный бот только для сотрудников: обращения приходят туда, ответы уходят клиенту через основного бота.")],
  ] as const
  return (
    <section className="card mb-4 space-y-4">
      <div className="flex items-center gap-2 font-medium"><Settings2 size={18} className="text-accent" />{tr("Настройки поддержки")}
        <button className="ml-auto text-xs text-muted hover:text-white" onClick={onClose}>{tr("Свернуть")}</button></div>
      <div className="grid gap-2 md:grid-cols-3">
        {modes.map(([id, title, desc]) => (
          <button key={id} onClick={() => set({ mode: id })}
                  className={`rounded-2xl border p-3 text-left transition ${c.mode === id ? 'border-accent bg-accent/10' : 'border-line hover:border-accent/40'}`}>
            <div className="text-sm font-medium">{title}</div><div className="mt-1 text-xs text-muted">{desc}</div>
          </button>
        ))}
      </div>
      {c.mode === 'staffbot' && (
        <div>
          <label className="label">{tr("Токен бота поддержки от @BotFather (второй бот, не клиентский)")}{c.staff_bot ? tr(" · сейчас @{0}", c.staff_bot) : ''}</label>
          <input className="input font-mono" value={token} onChange={(e) => setToken(e.target.value)} onFocus={() => token.includes('…') && setToken('')} placeholder="1234567890:AA..." />
          <div className="mt-1 text-xs text-muted">{tr("Каждый сотрудник пишет этому боту /start, а владелец указывает его Telegram ID в «Безопасность → Администраторы».")}</div>
        </div>
      )}
      {c.mode !== 'panel' && (
        <div>
          <div className="label">{tr("Кому пересылать обращения (роли)")}</div>
          <div className="flex flex-wrap gap-3 text-sm">
            {(Object.keys(ROLE_NAMES) as Role[]).filter((r) => r !== 'viewer').map((r) => (
              <label key={r} className="flex items-center gap-2">
                <input type="checkbox" className="size-4 accent-violet-500" checked={c.roles.includes(r)}
                       onChange={(e) => set({ roles: e.target.checked ? [...c.roles, r] : c.roles.filter((x) => x !== r) })} />{ROLE_NAMES[r]}
              </label>
            ))}
          </div>
          <div className="mt-1 text-xs text-muted">
            {tr("Получат:")}{' '}{c.staff.filter((s) => c.roles.includes(s.role) && s.tg).map((s) => s.username).join(', ') || tr("никто — укажите сотрудникам Telegram ID")}
          </div>
        </div>
      )}
      <div>
        <label className="label">{tr("Автоответ клиенту на новое обращение (пусто — без автоответа)")}</label>
        <input className="input" value={c.autoreply} onChange={(e) => set({ autoreply: e.target.value })} placeholder={tr("Спасибо, {name}! Мы ответим в течение 15 минут.")} />
      </div>
      <div className="space-y-2">
        <div className="label">{tr("Шаблоны быстрых ответов ·")}{' '}{VARS}</div>
        {c.templates.map((t, i) => (
          <div key={t.id} className="grid gap-2 rounded-xl bg-panel-2 p-2 md:grid-cols-[12rem_1fr_auto]">
            <input className="input" value={t.title} onChange={(e) => set({ templates: c.templates.map((x, j) => j === i ? { ...x, title: e.target.value } : x) })} placeholder={tr("Название")} />
            <textarea className="input h-16" value={t.text} onChange={(e) => set({ templates: c.templates.map((x, j) => j === i ? { ...x, text: e.target.value } : x) })} placeholder={tr("Текст ответа")} />
            <button className="btn btn-ghost px-2.5 text-red-300" onClick={() => set({ templates: c.templates.filter((_, j) => j !== i) })}><Trash2 size={14} /></button>
          </div>
        ))}
        <button className="btn btn-ghost py-1.5 text-sm" onClick={() => set({ templates: [...c.templates, { id: '', title: '', text: '' }] })}><Plus size={14} />{tr("Шаблон")}</button>
      </div>
      <div className="flex items-center gap-3">
        <button className="btn btn-primary" onClick={save}>{tr("Сохранить")}</button>
        {msg && <span className="text-sm text-muted">{msg}</span>}
      </div>
    </section>
  )
}

export default function Support({ owner }: { owner: boolean }) {
  const [threads, setThreads] = useState<Thread[] | null>(null)
  const [filter, setFilter] = useState<string>('active')
  const [open, setOpen] = useState<string | null>(null)
  const [conv, setConv] = useState<Conv | null>(null)
  const [tpls, setTpls] = useState<Tpl[]>([])
  const [text, setText] = useState('')
  const [err, setErr] = useState('')
  const [settings, setSettings] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  const loadThreads = () => api<{ threads: Thread[] }>(`/support?status=${filter}`).then((r) => setThreads(r.threads)).catch(() => {})
  const loadConv = (id: string) => api<Conv>(`/support/${id}`).then((c) => { setConv(c); setTimeout(() => end.current?.scrollIntoView(), 50) })

  useEffect(() => { loadThreads(); const t = setInterval(loadThreads, 15000); return () => clearInterval(t) }, [filter])
  useEffect(() => { api<Tpl[]>('/support/templates').then(setTpls).catch(() => {}) }, [settings])
  useEffect(() => {
    if (!open) { setConv(null); return }
    loadConv(open)
    api(`/support/${open}/read`, { body: {} }).then(loadThreads)
    const t = setInterval(() => loadConv(open), 10000)
    return () => clearInterval(t)
  }, [open])

  const send = async () => {
    if (!open || !text.trim()) return
    setErr('')
    try { await api(`/support/${open}`, { body: { text } }); setText(''); loadConv(open); loadThreads() } catch (e: any) { setErr(e.message) }
  }
  const status = (s: Status) => api(`/support/${open}/status`, { body: { status: s } }).then(() => { loadConv(open!); loadThreads() })
  const take = () => api(`/support/${open}/assign`, { body: {} }).then(() => { loadConv(open!); loadThreads() })

  return (
    <div className="max-w-6xl">
      <PageHeader title={tr("Поддержка")} icon={<LifeBuoy className="text-accent" />}
                  subtitle={tr("Обращения клиентов из Telegram-бота. Ответ уходит клиенту в бот. Сотрудники с ролью «Поддержка» видят только эту страницу и список клиентов.")}
                  actions={owner ? <button className="btn btn-ghost" onClick={() => setSettings(!settings)}><Settings2 size={16} />{tr("Настройки")}</button> : undefined} />
      {settings && owner && <SupportSettings onClose={() => setSettings(false)} />}
      <div className="grid gap-4 md:grid-cols-[19rem_1fr]">
        <div className={`card space-y-1 p-2 ${open ? 'hidden md:block' : ''}`}>
          <div className="mb-1 flex gap-1 rounded-xl bg-panel-2 p-1">
            {FILTERS.map(([id, label]) => (
              <button key={id} onClick={() => setFilter(id)}
                      className={`flex-1 rounded-lg px-2 py-1 text-xs transition ${filter === id ? 'bg-accent text-white' : 'text-muted hover:text-white'}`}>{label}</button>
            ))}
          </div>
          {threads === null && <div className="p-3 text-sm text-muted">{tr("Загрузка…")}</div>}
          {threads?.length === 0 && <div className="p-3 text-sm text-muted">{tr("Здесь пусто.")}</div>}
          {threads?.map((t) => (
            <button key={t.chat_id} onClick={() => setOpen(t.chat_id)}
                    className={`w-full rounded-xl px-3 py-2.5 text-left transition ${open === t.chat_id ? 'bg-accent/15' : 'hover:bg-panel-2'}`}>
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{t.label}</span>
                {t.unread > 0 && <span className="rounded-full bg-accent px-1.5 text-[11px] font-bold text-white">{t.unread}</span>}
              </div>
              <div className="truncate text-xs text-muted">{t.last_dir === 'out' ? tr("Вы: ") : ''}{t.last}</div>
              <div className="mt-1 flex items-center gap-2 text-[11px] text-muted/80">
                <span className={`pill px-1.5 py-0 text-[10px] ${STATUS[t.status][1]}`}>{STATUS[t.status][0]}</span>
                {t.assignee && <span>· {t.assignee}</span>}<span className="ml-auto">{relative(t.ts)}</span>
              </div>
            </button>
          ))}
        </div>

        <div className={`card flex min-h-[60vh] flex-col p-0 ${open ? '' : 'hidden md:flex'}`}>
          {!conv && <div className="m-auto p-6 text-sm text-muted">{tr("Выберите обращение слева")}</div>}
          {conv && <>
            <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
              <button className="md:hidden" onClick={() => setOpen(null)}><ArrowLeft size={18} /></button>
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{conv.label}</div>
                <div className="text-xs text-muted"><span className={`pill px-1.5 py-0 text-[10px] ${STATUS[conv.status][1]}`}>{STATUS[conv.status][0]}</span>
                  {conv.assignee ? tr(" · ответственный {0}", conv.assignee) : tr(" · никто не взял")}</div>
              </div>
              {conv.user_id && <a className="text-xs text-accent" href={`#user/${conv.user_id}`}>{tr("карточка клиента →")}</a>}
              {!conv.assignee && <button className="btn btn-ghost px-2.5 py-1 text-xs" onClick={take}><UserCheck size={13} />{tr("Взять себе")}</button>}
              {conv.status !== 'closed'
                ? <button className="btn btn-ghost px-2.5 py-1 text-xs text-emerald-300" onClick={() => status('closed')}><CheckCircle2 size={13} />{tr("Закрыть")}</button>
                : <button className="btn btn-ghost px-2.5 py-1 text-xs" onClick={() => status('open')}><RotateCcw size={13} />{tr("Открыть снова")}</button>}
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto p-4" style={{ maxHeight: '55vh' }}>
              {conv.messages.map((m) => (
                <div key={m.id} className={`flex ${m.dir === 'out' ? 'justify-end' : ''}`}>
                  <div className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${m.dir === 'out' ? 'bg-accent/25' : 'bg-panel-2'}`}>
                    {m.text}
                    <div className="mt-1 text-[10px] text-muted">{m.dir === 'out' && m.admin ? `${m.admin} · ` : ''}{relative(m.ts)}</div>
                  </div>
                </div>
              ))}
              <div ref={end} />
            </div>
            {tpls.length > 0 && (
              <div className="flex flex-wrap gap-1.5 border-t border-line px-3 pt-2">
                {tpls.map((t) => (
                  <button key={t.id} title={t.text} onClick={() => setText((x) => (x ? x + '\n' : '') + t.text)}
                          className="rounded-full border border-line bg-panel-2 px-2.5 py-1 text-xs text-muted hover:border-accent/50 hover:text-white">📝 {t.title}</button>
                ))}
              </div>
            )}
            <div className="flex gap-2 p-3">
              <textarea className="input h-16 flex-1 resize-none" value={text} onChange={(e) => setText(e.target.value)} placeholder={tr("Ответ клиенту… (можно {name}, {link}, {expire}, {days})")}
                        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
              <button className="btn btn-primary" disabled={!text.trim()} onClick={send}><Send size={16} /></button>
            </div>
            {err && <div className="px-3 pb-3 text-sm text-red-300">{err}</div>}
          </>}
        </div>
      </div>
    </div>
  )
}
