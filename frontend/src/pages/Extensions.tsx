import { useEffect, useState, type ReactNode } from 'react'
import { Activity, Ban, ShieldAlert, Bell, Bot, ChevronDown, Cloud, CreditCard, DatabaseBackup, FileBarChart, Gauge, Gift, Handshake, LifeBuoy, Link2, Megaphone, Network, Puzzle, Radar, Route, Send, Shuffle, Ticket, Users } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { api, type Plan } from '../api'
import { PageHeader, Switch } from '../components/brand'
import { AlertsCard, BackupsCard } from '../components/SecurityCards'
import { ProbeCard } from '../components/SettingsExtra'
import Storages from '../components/Storages'
import { PaymentsCard, PromoCard } from '../components/Commerce'
import { ZapretCard } from '../components/ZapretCard'
import { tr } from '../i18n'

type Ext = {
  bot: { enabled: boolean; username: string | null }
  mtproto: { enabled: boolean }
  probe: { enabled: boolean; hide_failed: boolean }
  alerts: { enabled: boolean }
  backup: { enabled: boolean; hour: number; storages: number }
  smartlink: { enabled: boolean }
  adblock: { enabled: boolean }
  trial: { enabled?: boolean; plan_id?: number | null; days?: number; gb?: number }
  l2tp: { enabled: boolean; installed: boolean; services: Record<string, string>; psk: string; dns: string; sessions: { iface: string; user: string; ip: string }[] }
  payments: { providers: { name: string; enabled: boolean; ready: boolean }[] }
  referral: { enabled: boolean; bonus_days: number; friend_days: number }
  promo: { enabled: boolean }
  support: { enabled: boolean }
  family: { enabled: boolean }
  routing: { enabled: boolean; extra_direct: string[] }
  warp: { enabled: boolean; domains: string[]; registered: boolean; default_domains: string[] }
  status: { enabled: boolean; title: string }
  failover: { enabled: boolean }
  report: { enabled: boolean; weekday: number; hour: number }
  speed: { enabled: boolean }
}

const WEEKDAYS = [tr("понедельник"), tr("вторник"), tr("среда"), tr("четверг"), tr("пятница"), tr("суббота"), tr("воскресенье")]

/** Text list edited in a textarea (one item per line). */
function ListOption({ label, value, placeholder, onSave }: { label: string; value: string[]; placeholder: string; onSave: (v: string[]) => void }) {
  const [text, setText] = useState(value.join('\n'))
  return (
    <div className="space-y-2">
      <label className="label">{label}</label>
      <textarea className="input h-24 font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} />
      <button className="btn btn-ghost py-1.5 text-sm" onClick={() => onSave(text.split(/[\s,]+/).map((x) => x.trim()).filter(Boolean))}>{tr("Сохранить")}</button>
    </div>
  )
}

function ExtCard({ icon, title, desc, on, onToggle, status, children, color = 'text-accent', busy }: {
  icon: ReactNode; title: string; desc: ReactNode; on?: boolean; onToggle?: (v: boolean) => void; status?: ReactNode
  children?: ReactNode; color?: string; busy?: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <section className={`card flex flex-col gap-3 transition ${on ? 'border-accent/30' : ''}`}>
      <div className="flex items-start gap-3">
        <div className={`grid size-11 shrink-0 place-items-center rounded-2xl bg-panel-2 ${color}`}>{icon}</div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 font-semibold">{title}{status}</div>
          <div className="mt-0.5 text-sm text-muted">{desc}</div>
        </div>
        {onToggle && <Switch on={!!on} onChange={onToggle} disabled={busy} />}
      </div>
      {children && (
        <>
          <button className="flex items-center gap-1 self-start text-xs text-muted hover:text-white" onClick={() => setOpen(!open)}>
            <ChevronDown size={14} className={`transition ${open ? 'rotate-180' : ''}`} />{open ? tr("Свернуть") : tr("Настроить")}
          </button>
          {open && <div className="space-y-3 border-t border-line pt-3">{children}</div>}
        </>
      )}
    </section>
  )
}

const on = (t: string) => <span className="pill bg-emerald-500/15 text-emerald-300">{t}</span>
const off = (t = tr("выключено")) => <span className="pill bg-zinc-500/20 text-zinc-400">{t}</span>

function BotSettings({ reload }: { reload: () => void }) {
  const [token, setToken] = useState('')
  const [msg, setMsg] = useState('')
  const save = (v: string) => api<{ username: string | null }>('/telegram-bot', { method: 'PUT', body: { token: v } })
    .then((r) => { setMsg(v ? tr("Подключён @{0}", r.username) : tr("Бот отключён")); setToken(''); reload() }).catch((e) => setMsg(e.message))
  return (
    <div className="space-y-2">
      <div className="text-sm text-muted">{tr("Бот пишет клиентам за 3 дня до окончания и при 90% трафика; клиент присылает боту свою ссылку или ключ — бот сам узнаёт аккаунт и привязывает Telegram. Команды для вас — /help.")}</div>
      <label className="label">{tr("Токен от @BotFather (/newbot)")}</label>
      <div className="flex flex-wrap gap-2">
        <input className="input min-w-60 flex-1 font-mono" value={token} onChange={(e) => setToken(e.target.value)} placeholder="1234567890:AA..." />
        <button className="btn btn-primary" disabled={!token.trim()} onClick={() => save(token.trim())}>{tr("Сохранить")}</button>
        <button className="btn btn-danger" onClick={() => save('')}>{tr("Отключить")}</button>
      </div>
      {msg && <div className="text-sm text-muted">{msg}</div>}
    </div>
  )
}

function MtprotoLinks() {
  const [tg, setTg] = useState<{ enabled: boolean; links: { via: string; host: string; port: number; https: string }[] } | null>(null)
  useEffect(() => { api('/telegram').then(setTg) }, [])
  if (!tg?.enabled) return <div className="text-sm text-muted">{tr("Включите дополнение, чтобы получить ссылки.")}</div>
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {tg.links.map((l) => (
        <div key={l.host} className="flex gap-3 rounded-xl bg-bg/40 p-3">
          <div className="shrink-0 rounded-lg bg-white p-1.5"><QRCodeSVG value={l.https} size={84} /></div>
          <div className="min-w-0 text-xs">
            <div className="mb-1 font-medium">{l.via ? tr("📱 через {0}", l.via) : tr("🏠 напрямую")}</div>
            <input className="input font-mono text-[11px]" readOnly value={l.https} onFocus={(e) => e.target.select()} />
            <a className="mt-2 inline-block text-accent" href={l.https} target="_blank" rel="noopener">{tr("Открыть в Telegram →")}</a>
          </div>
        </div>
      ))}
    </div>
  )
}

function Broadcast() {
  const [text, setText] = useState('')
  const [target, setTarget] = useState('active')
  const [msg, setMsg] = useState('')
  return (
    <div className="space-y-2">
      <textarea className="input h-24" value={text} onChange={(e) => setText(e.target.value)} placeholder={tr("Например: плановые работы сегодня 23:00–23:10, обновите подписку")} />
      <div className="flex flex-wrap gap-2">
        <select className="input w-auto" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="active">{tr("Активным клиентам")}</option><option value="expiring">{tr("Истекают в 7 дней")}</option><option value="all">{tr("Всем с Telegram")}</option>
        </select>
        <button className="btn btn-primary" disabled={!text.trim()} onClick={() => api<{ sent: number; total: number }>('/broadcast', { body: { text, target } })
          .then((r) => { setMsg(tr("Отправлено {0} из {1}", r.sent, r.total)); setText('') }).catch((e) => setMsg(e.message))}><Send size={15} />{tr("Отправить")}</button>
      </div>
      {msg && <div className="text-sm text-muted">{msg}</div>}
    </div>
  )
}

export default function Extensions() {
  const [ext, setExt] = useState<Ext | null>(null)
  const [plans, setPlans] = useState<Plan[]>([])
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const load = () => api<Ext>('/extensions').then(setExt)
  useEffect(() => { load(); api<Plan[]>('/plans').then(setPlans).catch(() => {}) }, [])
  const toggle = async (name: string, enabled: boolean, options: object = {}) => {
    setBusy(name); setErr('')
    try { await api(`/extensions/${name}`, { method: 'PUT', body: { enabled, options } }); await load() } catch (e: any) { setErr(e.message) } finally { setBusy('') }
  }
  if (!ext) return <div className="text-muted">{tr("Загрузка…")}</div>
  const t = ext.trial

  return (
    <div className="max-w-6xl">
      <PageHeader title={tr("Дополнения")} icon={<Puzzle className="text-accent" />}
                  subtitle={tr("Всё, что включается отдельно: автоматизация, интеграции и расширения. Выключенные дополнения не расходуют ресурсы сервера.")} />
      {err && <div className="mb-4 rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</div>}

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted/80">{tr("Клиенты и Telegram")}</h2>
      <div className="mb-8 grid gap-4 lg:grid-cols-2">
        <ExtCard icon={<Bot size={22} />} color="text-sky-400" title={tr("Telegram-бот")} desc={tr("Напоминания клиентам, привязка по ключу, пробный период, управление через Telegram.")}
                 status={ext.bot.enabled ? on(`@${ext.bot.username ?? '…'}`) : off(tr("не подключён"))}>
          <BotSettings reload={load} />
        </ExtCard>
        <ExtCard icon={<Link2 size={22} />} color="text-accent-2" title={tr("Умная ссылка")} on={ext.smartlink.enabled} onToggle={(v) => toggle('smartlink', v)}
                 desc={tr("Одна короткая ссылка на клиента: в браузере — страница под его устройство (Android, iPhone, Windows, Mac) с кнопками установки и импорта; в приложении — подписка.")} />
        <ExtCard icon={<Gift size={22} />} color="text-pink-400" title={tr("Пробный период")} on={!!t.enabled} busy={busy === 'trial'}
                 onToggle={(v) => toggle('trial', v, { days: t.days ?? 1, gb: t.gb ?? 2, plan_id: t.plan_id ?? null })}
                 desc={tr("Новый человек пишет боту /trial и сразу получает доступ (один раз на Telegram-аккаунт). Вам приходит уведомление.")}>
          <div className="grid gap-2 sm:grid-cols-3">
            <div><label className="label">{tr("Дней")}</label><input className="input" type="number" min={1} defaultValue={t.days ?? 1} id="trial-days" /></div>
            <div><label className="label">{tr("Трафик, ГБ")}</label><input className="input" type="number" min={0} defaultValue={t.gb ?? 2} id="trial-gb" /></div>
            <div><label className="label">{tr("Или тариф")}</label><select className="input" defaultValue={t.plan_id ?? ''} id="trial-plan">
              <option value="">{tr("— дни и ГБ —")}</option>{plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
          </div>
          <button className="btn btn-ghost" onClick={() => toggle('trial', !!t.enabled, {
            days: Number((document.getElementById('trial-days') as HTMLInputElement).value), gb: Number((document.getElementById('trial-gb') as HTMLInputElement).value),
            plan_id: Number((document.getElementById('trial-plan') as HTMLSelectElement).value) || null })}>{tr("Сохранить")}</button>
        </ExtCard>
        <ExtCard icon={<LifeBuoy size={22} />} color="text-emerald-300" title={tr("Поддержка в боте")} on={ext.support.enabled} busy={busy === 'support'} onToggle={(v) => toggle('support', v)}
                 desc={<>{tr("Клиент пишет боту вопрос — он приходит вам в Telegram и во вкладку")}{' '}<a className="text-accent" href="#support">{tr("«Поддержка»")}</a>{tr(". Ответить можно прямо в Telegram (Ответить на сообщение) или из панели.")}</>} />
        <ExtCard icon={<Megaphone size={22} />} color="text-amber-300" title={tr("Рассылка")} desc={tr("Сообщение всем клиентам через бота: работы на сервере, новые серверы, акции.")}>
          <Broadcast />
        </ExtCard>
      </div>

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted/80">{tr("Продажи")}</h2>
      <div className="mb-8 grid gap-4 lg:grid-cols-2">
        <div className="lg:col-span-2">
          <ExtCard icon={<CreditCard size={22} />} color="text-lime-300" title={tr("Онлайн-оплата")}
                   status={ext.payments.providers.some((p) => p.enabled && p.ready)
                     ? on(tr("подключено: {0}", ext.payments.providers.filter((p) => p.enabled && p.ready).length)) : off(tr("не подключена"))}
                   desc={tr("ЮKassa (карты, СБП), CryptoBot и NOWPayments (криптовалюта), Telegram Stars, перевод по реквизитам. Всё готово — осталось вписать ключи. Клиенты платят в боте и на своей странице, доступ продлевается сам.")}>
            <PaymentsCard />
          </ExtCard>
        </div>
        <ExtCard icon={<Ticket size={22} />} color="text-pink-300" title={tr("Промокоды")} on={ext.promo.enabled} busy={busy === 'promo'} onToggle={(v) => toggle('promo', v)}
                 desc={tr("Скидка на следующую оплату или бесплатные дни. Клиент вводит код в боте (/promo) или на своей странице.")}>
          <PromoCard />
        </ExtCard>
        <ExtCard icon={<Handshake size={22} />} color="text-amber-300" title={tr("Реферальная программа")} on={ext.referral.enabled} busy={busy === 'referral'}
                 onToggle={(v) => toggle('referral', v, { bonus_days: ext.referral.bonus_days, friend_days: ext.referral.friend_days })}
                 desc={tr("У каждого клиента своя ссылка на бота. Друг оплатил первый раз — оба получают бонусные дни автоматически.")}>
          <div className="grid gap-2 sm:grid-cols-2">
            <div><label className="label">{tr("Пригласившему, дней")}</label><input className="input" type="number" min={0} defaultValue={ext.referral.bonus_days} id="ref-bonus" /></div>
            <div><label className="label">{tr("Другу, дней")}</label><input className="input" type="number" min={0} defaultValue={ext.referral.friend_days} id="ref-friend" /></div>
          </div>
          <button className="btn btn-ghost py-1.5 text-sm" onClick={() => toggle('referral', ext.referral.enabled, {
            bonus_days: Number((document.getElementById('ref-bonus') as HTMLInputElement).value), friend_days: Number((document.getElementById('ref-friend') as HTMLInputElement).value) })}>{tr("Сохранить")}</button>
        </ExtCard>
        <ExtCard icon={<Users size={22} />} color="text-sky-300" title={tr("Семейный доступ")} on={ext.family.enabled} busy={busy === 'family'} onToggle={(v) => toggle('family', v)}
                 desc={tr("Один оплачивает — пользуется семья: у каждого свои ключи и устройства, общий срок и общий лимит трафика. Участники добавляются в карточке клиента; размер семьи задаётся в тарифе.")} />
      </div>

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted/80">{tr("Протоколы и сеть")}</h2>
      <div className="mb-8 grid gap-4 lg:grid-cols-2">
        <ExtCard icon={<Send size={22} />} color="text-sky-400" title={tr("Прокси для Telegram (MTProto)")} on={ext.mtproto.enabled} busy={busy === 'mtproto'} onToggle={(v) => toggle('mtproto', v)}
                 desc={tr("Telegram работает без VPN-приложения. Маскировка Fake-TLS под ваш домен.")}>
          <MtprotoLinks />
        </ExtCard>
        <ExtCard icon={<Network size={22} />} color="text-violet-300" title="L2TP/IPsec" on={ext.l2tp.enabled} busy={busy === 'l2tp'} onToggle={(v) => toggle('l2tp', v)}
                 status={busy === 'l2tp' ? <span className="pill bg-amber-500/15 text-amber-300">{tr("устанавливаю…")}</span> : ext.l2tp.enabled && on(tr("сессий {0}", ext.l2tp.sessions.length))}
                 desc={tr("Встроенный VPN Windows, macOS, iOS и Android — клиенту включается в карточке, получает логин и пароль. Удобно, чтобы отдельно туннелировать рабочие программы.")}>
          <div className="rounded-xl bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            {tr("Из российских сетей IPsec обычно блокируется ТСПУ (проверено: пакеты IKE с нашей точки входа до сервера не доходят). Подходит клиентам за рубежом и в сетях без фильтрации.")}
          </div>
          {ext.l2tp.enabled && (
            <div className="grid gap-2 text-sm sm:grid-cols-2">
              <div>{tr("Общий ключ (PSK):")}{' '}<code className="text-accent">{ext.l2tp.psk}</code></div>
              <div>{tr("Службы:")}{' '}{Object.entries(ext.l2tp.services).map(([k, v]) => `${k} ${v}`).join(', ')}</div>
              {ext.l2tp.sessions.map((s) => <div key={s.iface} className="text-xs text-muted">🟢 {s.user} · {s.ip} · {s.iface}</div>)}
            </div>
          )}
        </ExtCard>
        <ExtCard icon={<Route size={22} />} color="text-emerald-300" title={tr("Российские сайты напрямую (Happ)")} on={ext.routing.enabled} busy={busy === 'routing'}
                 onToggle={(v) => toggle('routing', v, { extra_direct: ext.routing.extra_direct })}
                 desc={tr("Госуслуги, банки, маркетплейсы и все сайты .ru/.рф идут мимо VPN с российского IP, остальное — через VPN. Профиль маршрутизации приходит в Happ вместе с подпиской и включается сам.")}>
          <ListOption label={tr("Дополнительно напрямую (домены, по одному в строке)")} value={ext.routing.extra_direct} placeholder={'mycompany.com\nvk.com'}
                      onSave={(v) => toggle('routing', ext.routing.enabled, { extra_direct: v })} />
        </ExtCard>
        <ExtCard icon={<Cloud size={22} />} color="text-orange-300" title={tr("WARP для ChatGPT, Gemini и др.")} on={ext.warp.enabled} busy={busy === 'warp'}
                 onToggle={(v) => toggle('warp', v, { domains: ext.warp.domains })}
                 status={ext.warp.enabled && ext.warp.registered ? on('Cloudflare') : undefined}
                 desc={tr("Сервисы, которые блокируют IP дата-центров, получают трафик через Cloudflare WARP (бесплатный аккаунт регистрируется сам). Остальной трафик идёт как обычно.")}>
          <div className="text-xs text-muted">{tr("Уже включены:")}{' '}{ext.warp.default_domains.join(', ')}</div>
          <ListOption label={tr("Добавить домены")} value={ext.warp.domains} placeholder={'spotify.com\nopenai.com'}
                      onSave={(v) => toggle('warp', ext.warp.enabled, { domains: v })} />
        </ExtCard>
        <ExtCard icon={<Gauge size={22} />} color="text-cyan-300" title={tr("Ограничение скорости")} on={ext.speed.enabled} busy={busy === 'speed'} onToggle={(v) => toggle('speed', v)}
                 desc={tr("Скорость на клиента задаётся в тарифе или в карточке клиента (Мбит/с, в обе стороны). Работает через основной сервер для любых входов, включая точку входа в РФ.")} />
        <ExtCard icon={<ShieldAlert size={22} />} color="text-amber-300" title={tr("Обход DPI на точках входа (zapret)")}
                 desc={tr("Стратегии как в «Запрете» для пути «точка входа → основной сервер»: включаются сами, только если провайдер точки начнёт блокировать, и обновляются из репозитория каждые 6 часов.")}>
          <ZapretCard />
        </ExtCard>
        <ExtCard icon={<Ban size={22} />} color="text-red-300" title={tr("Блокировка рекламы и трекеров")} on={ext.adblock.enabled} busy={busy === 'adblock'} onToggle={(v) => toggle('adblock', v)}
                 desc={tr("Реклама и трекеры отсекаются на сервере для всех клиентов (список geosite:category-ads-all) — меньше трафика, быстрее страницы. Действует на всех серверах кластера.")} />
      </div>

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted/80">{tr("Надёжность и мониторинг")}</h2>
      <div className="mb-8 grid gap-4 lg:grid-cols-2">
        <ExtCard icon={<DatabaseBackup size={22} />} color="text-emerald-300" title={tr("Бэкапы и облака")} on={ext.backup.enabled}
                 status={ext.backup.storages ? on(tr("облаков: {0}", ext.backup.storages)) : undefined}
                 desc={tr("Ежедневный архив базы в Telegram владельцам и в облака: Яндекс Диск, Облако Mail.ru, Google Drive, Dropbox, OneDrive, S3, WebDAV, SFTP.")}>
          <BackupsCard />
          <Storages />
        </ExtCard>
        <ExtCard icon={<Bell size={22} />} color="text-amber-300" title={tr("Оповещения")} on={ext.alerts.enabled} desc={tr("🔴/🟢 владельцам в Telegram: сбои серверов и точек входа, перегрузка, сертификаты, блокировки ключей, смена IP.")}>
          <AlertsCard />
        </ExtCard>
        <ExtCard icon={<Radar size={22} />} color="text-accent-2" title={tr("Проверка ключей из РФ")} on={ext.probe.enabled}
                 desc={tr("Точка входа в РФ каждые 10 минут проверяет все ключи всех серверов; нерабочие скрываются из подписок.")}>
          <ProbeCard />
        </ExtCard>
        <ExtCard icon={<Shuffle size={22} />} color="text-sky-300" title={tr("Автопереключение серверов")} on={ext.failover.enabled} busy={busy === 'failover'}
                 onToggle={(v) => toggle('failover', v)}
                 desc={tr("Если точка входа или узел недоступны дольше 2–3 минут, их ключи убираются из подписок; приложения обновляют подписку каждый час и переходят на рабочие серверы. Вернётся сервер — ключи вернутся.")} />
        <ExtCard icon={<Activity size={22} />} color="text-emerald-300" title={tr("Страница статуса")} on={ext.status.enabled} busy={busy === 'status'}
                 onToggle={(v) => toggle('status', v, { title: ext.status.title })}
                 status={ext.status.enabled ? <a className="pill bg-emerald-500/15 text-emerald-300" href={`${location.origin}/status`} target="_blank" rel="noopener">{tr("открыть ↗")}</a> : undefined}
                 desc={tr("Публичная страница для клиентов: работают ли серверы и доступность за 30 дней (без IP-адресов). Ссылка появляется на странице клиента.")}>
          <div><label className="label">{tr("Ссылка")}</label><input className="input font-mono text-xs" readOnly value={`${location.origin}/status`} onFocus={(e) => e.target.select()} /></div>
          <div><label className="label">{tr("Заголовок")}</label><input className="input" defaultValue={ext.status.title} id="status-title" /></div>
          <button className="btn btn-ghost py-1.5 text-sm" onClick={() => toggle('status', ext.status.enabled, { title: (document.getElementById('status-title') as HTMLInputElement).value })}>{tr("Сохранить")}</button>
        </ExtCard>
        <ExtCard icon={<FileBarChart size={22} />} color="text-violet-300" title={tr("Еженедельный отчёт")} on={ext.report.enabled} busy={busy === 'report'}
                 onToggle={(v) => toggle('report', v, { weekday: ext.report.weekday, hour: ext.report.hour })}
                 desc={tr("Раз в неделю владельцам в Telegram: новые клиенты, оплаты, трафик, топ, кто истекает, доступность серверов, неотвеченные обращения.")}>
          <div className="grid gap-2 sm:grid-cols-2">
            <div><label className="label">{tr("День")}</label><select className="input" defaultValue={ext.report.weekday} id="rep-day">
              {WEEKDAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}</select></div>
            <div><label className="label">{tr("Час (время сервера)")}</label><input className="input" type="number" min={0} max={23} defaultValue={ext.report.hour} id="rep-hour" /></div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-ghost py-1.5 text-sm" onClick={() => toggle('report', ext.report.enabled, {
              weekday: Number((document.getElementById('rep-day') as HTMLSelectElement).value), hour: Number((document.getElementById('rep-hour') as HTMLInputElement).value) })}>{tr("Сохранить")}</button>
            <button className="btn btn-ghost py-1.5 text-sm" onClick={() => api('/report/send', { body: {} }).then(() => setErr('')).catch((e) => setErr(e.message))}>{tr("Прислать сейчас")}</button>
          </div>
        </ExtCard>
      </div>
    </div>
  )
}
