import { useEffect, useState } from 'react'
import { Check, Copy, KeyRound, RefreshCcw, Send, Trash2 } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from 'recharts'
import { api, type UserDetail as Detail } from '../api'
import { bytes, date, relative } from '../format'
import { Modal, Progress, StatusBadge } from '../components/ui'
import ExtendPanel from '../components/ExtendPanel'
import { FamilyBlock, GrowthBlock, ShareHero } from '../components/ClientExtras'
import { tr } from '../i18n'

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button className="btn btn-ghost px-2.5 py-1.5" title={tr("Копировать")}
            onClick={() => navigator.clipboard.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500) })}>
      {done ? <Check size={15} className="text-accent" /> : <Copy size={15} />}
    </button>
  )
}

const toDateInput = (ts: number | null) => (ts ? new Date(ts * 1000).toISOString().slice(0, 10) : '')

// Two-step button: the confirmation appears on the button itself, so it can't end up off-screen.
export function ConfirmButton({ onConfirm, children, confirmText, className = 'btn btn-danger' }:
  { onConfirm: () => void; children: React.ReactNode; confirmText: string; className?: string }) {
  const [armed, setArmed] = useState(false)
  useEffect(() => {
    if (!armed) return
    const t = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(t)
  }, [armed])
  return (
    <button className={`${className} ${armed ? 'animate-pulse ring-2 ring-red-400' : ''}`}
            onClick={(e) => { e.stopPropagation(); armed ? (setArmed(false), onConfirm()) : setArmed(true) }}>
      {armed ? confirmText : children}
    </button>
  )
}

function Toggle({ on, onChange, label, hint }: { on: boolean; onChange: (v: boolean) => void; label: string; hint: string }) {
  return (
    <button type="button" onClick={() => onChange(!on)} className="flex items-center gap-3 rounded-xl bg-panel-2 px-3 py-2 text-left">
      <span className={`relative h-6 w-11 shrink-0 rounded-full transition ${on ? 'bg-accent' : 'bg-zinc-600'}`}>
        <span className={`absolute top-0.5 size-5 rounded-full bg-white transition-all ${on ? 'left-5.5' : 'left-0.5'}`} />
      </span>
      <span>
        <span className="block text-sm font-medium">{label}</span>
        <span className="block text-xs text-muted">{hint}</span>
      </span>
    </button>
  )
}

export default function UserDetail({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const [u, setU] = useState<Detail | null>(null)
  const [qr, setQr] = useState<string>('sub')
  const [limit, setLimit] = useState('')
  const [expire, setExpire] = useState('')
  const [note, setNote] = useState('')
  const [tgId, setTgId] = useState('')
  const [speed, setSpeed] = useState('')
  const [msg, setMsg] = useState('')

  const load = () => api<Detail>(`/users/${id}`).then((d) => {
    setU(d)
    setLimit(d.data_limit ? String(+(d.data_limit / 1024 ** 3).toFixed(2)) : '0')
    setExpire(toDateInput(d.expire_at))
    setNote(d.note)
    setTgId(d.tg_id)
    setSpeed(String(d.speed_mbps || 0))
  })
  useEffect(() => {
    load()
    // live device status; refresh only the data, not the form fields being edited
    const t = setInterval(() => api<Detail>(`/users/${id}`).then(setU).catch(() => {}), 5000)
    return () => clearInterval(t)
  }, [id])

  async function act(fn: () => Promise<unknown>, text: string) {
    await fn()
    await load()
    onChanged()
    setMsg(text)
    setTimeout(() => setMsg(''), 2000)
  }

  if (!u) return <Modal title="…" onClose={onClose} wide><div className="text-muted">{tr("Загрузка…")}</div></Modal>

  const save = () => act(() => api(`/users/${id}`, {
    method: 'PATCH',
    body: {
      data_limit_gb: Number(limit) || 0, note, tg_id: tgId.trim(), speed_mbps: Number(speed) || 0,
      ...(expire ? { expire_at: Math.floor(new Date(expire + 'T23:59:59').getTime() / 1000) } : { clear_expire: true }),
    },
  }), tr("Сохранено"))

  const qrValue = qr === 'sub' ? u.smart_link : u.links.find((l) => l.key === qr)?.url ?? u.smart_link

  return (
    <Modal title={u.username} onClose={onClose} wide>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={u.status} online={u.online} />
          <span className="text-sm text-muted">{tr("создан")}{' '}{date(u.created_at)}{' '}{tr("· активность")}{' '}{relative(u.last_online)}</span>
          {u.pending_signup && <span className="pill bg-amber-500/15 text-amber-300">{tr("ждёт первой оплаты")}</span>}
          {msg && <span className="ml-auto text-sm text-accent">{msg}</span>}
        </div>

        <ShareHero u={u} />

        <div className="flex flex-wrap items-center gap-2">
          <Toggle on={u.multi_device} label={tr("Мультиаккаунт")}
                  hint={u.multi_device ? tr("ключ работает на любом числе устройств") : tr("одновременно только 1 устройство")}
                  onChange={(v) => act(() => api(`/users/${id}`, { method: 'PATCH', body: { multi_device: v } }),
                    v ? tr("Мультиаккаунт включён") : tr("Теперь только 1 устройство"))} />
          <Toggle on={u.reset_monthly} label={tr("Сброс трафика")}
                  hint={u.reset_monthly ? tr("каждые 30 дней автоматически") : tr("выключен")}
                  onChange={(v) => act(() => api(`/users/${id}`, { method: 'PATCH', body: { reset_monthly: v } }),
                    v ? tr("Трафик будет сбрасываться каждые 30 дней") : tr("Автосброс выключен"))} />
          <Toggle on={u.l2tp_enabled} label="L2TP/IPsec"
                  hint={u.l2tp_enabled ? tr("встроенный VPN включён") : tr("выключен")}
                  onChange={(v) => act(() => api(`/users/${id}`, { method: 'PATCH', body: { l2tp_enabled: v } }), v ? tr("L2TP включён") : tr("L2TP выключен"))} />
          <Toggle on={u.hide_ip} label={tr("Скрыть IP сервера")}
                  hint={u.hide_ip ? tr("в ключах домены вместо IP") : tr("в ключах IP-адреса")}
                  onChange={(v) => act(() => api(`/users/${id}`, { method: 'PATCH', body: { hide_ip: v } }), v ? tr("IP скрыт — клиенту нужно обновить подписку") : tr("В ключах снова IP"))} />
          <Toggle on={u.enabled} label={tr("Доступ")} hint={u.enabled ? tr("пользователь включён") : tr("пользователь отключён")}
                  onChange={(v) => act(() => api(`/users/${id}`, { method: 'PATCH', body: { enabled: v } }), v ? tr("Включён") : tr("Отключён"))} />
          <ConfirmButton className="btn btn-danger sm:ml-auto" confirmText={tr("Нажмите ещё раз — удалить")}
                         onConfirm={async () => { await api(`/users/${id}`, { method: 'DELETE' }); onChanged(); onClose() }}>
            <Trash2 size={16} />{tr("Удалить")}
          </ConfirmButton>
        </div>

        {u.l2tp_enabled && (u.l2tp ? (
          <div className="rounded-2xl border border-violet-500/30 bg-violet-500/5 p-3 text-sm">
            <div className="mb-2 flex items-center gap-2 font-medium text-violet-300">L2TP/IPsec {u.l2tp.online && <span className="pill bg-emerald-500/15 text-emerald-300">{tr("● подключён")}</span>}</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {([[tr("Сервер"), u.l2tp.server], [tr("Общий ключ (PSK)"), u.l2tp.psk], [tr("Логин"), u.l2tp.login], [tr("Пароль"), u.l2tp.password]] as const).map(([k, v]) => (
                <div key={k}><div className="label">{k}</div><div className="flex gap-2"><input className="input font-mono text-xs" readOnly value={v} /><CopyButton text={v} /></div></div>
              ))}
            </div>
            <details className="mt-2 text-xs text-muted"><summary className="cursor-pointer">{tr("Как подключить")}</summary>
              <div className="mt-1 space-y-1">
                <div><b>Windows:</b>{' '}{tr("Параметры → Сеть → VPN → Добавить: тип «L2TP/IPsec с общим ключом», ввести сервер, ключ, логин, пароль.")}</div>
                <div><b>iPhone/Mac:</b>{' '}{tr("Настройки → VPN → Добавить → L2TP → сервер, учётная запись, пароль, «Общий ключ».")}</div>
                <div><b>Android:</b>{' '}{tr("Настройки → Сеть → VPN → «L2TP/IPSec PSK» (на новых версиях Android нужен сторонний клиент, например strongSwan не подойдёт — используйте основной ключ).")}</div>
                <div>{tr("Трафик L2TP учитывается в общем лимите клиента, сессия считается отдельным устройством.")}</div>
              </div>
            </details>
          </div>
        ) : <div className="rounded-xl bg-amber-500/10 px-3 py-2 text-xs text-amber-300">{tr("L2TP включён клиенту, но дополнение L2TP выключено — включите его в «Дополнениях».")}</div>)}

        <ExtendPanel userId={id} planId={u.plan_id} onDone={(m) => { load(); onChanged(); setMsg(m); setTimeout(() => setMsg(''), 2500) }} />
        <GrowthBlock u={u} reload={load} />
        <FamilyBlock u={u} reload={() => { load(); onChanged() }} />

        <div className="rounded-2xl bg-panel-2 p-3">
          <div className="mb-2 flex flex-wrap items-center gap-x-2 text-xs font-medium text-muted">
            <span>{tr("Сейчас подключено:")}{' '}<span className="text-base text-white">{u.devices.filter((d) => d.online).length}</span></span>
            {u.devices.some((d) => d.blocked) && <span>{tr("· заблокировано лимитом:")}{' '}<span className="text-red-300">{u.devices.filter((d) => d.blocked).length}</span></span>}
            <span>{tr("· зарегистрировано устройств:")}{' '}{u.devices.filter((d) => d.kind === 'device').length}</span>
          </div>
          {u.devices.length === 0 && (
            <div className="text-xs text-muted">
              {tr("Устройства появятся здесь после загрузки подписки. Точно различаются устройства, добавившие VPN ссылкой-подпиской в приложении, которое передаёт ID устройства (Happ, v2RayTun). Подключения по общему ключу считаются по IP.")}
            </div>
          )}
          <div className="divide-y divide-line/60">
            {u.devices.map((d) => (
              <div key={d.id ?? `ip-${d.ips[0]}`} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                <span className={`size-2.5 shrink-0 rounded-full ${d.blocked ? 'bg-red-400' : d.online ? 'animate-pulse bg-emerald-400' : 'bg-zinc-600'}`} />
                <div className="min-w-0 flex-1">
                  <div className={`truncate font-medium ${d.enabled ? '' : 'text-muted line-through'}`}>
                    {d.kind === 'ip' ? `🌐 ${d.name}` : `📱 ${d.name}`}
                    {d.os && <span className="ml-2 text-xs font-normal text-muted">{d.os}</span>}
                  </div>
                  <div className="truncate text-xs text-muted">
                    {d.blocked ? <span className="text-red-300">{tr("заблокировано (лимит 1 устройство)")}</span>
                      : d.online ? <span className="text-emerald-300">{tr("онлайн")}</span>
                      : tr("был {0}", relative(d.last_seen))}
                    {d.ips.length > 0 && <span className="ml-2 font-mono">{d.ips.join(', ')}</span>}
                    {d.app && <span className="ml-2">{d.app}</span>}
                  </div>
                </div>
                {d.kind === 'device' && d.id !== null && (
                  <div className="flex gap-1.5">
                    <button className="btn btn-ghost px-2.5 py-1 text-xs"
                            onClick={() => act(() => api(`/users/${id}/devices/${d.id}`, { method: 'PATCH', body: { enabled: !d.enabled } }),
                              d.enabled ? tr("Устройство отключено") : tr("Устройство включено"))}>
                      {d.enabled ? tr("Отключить") : tr("Включить")}
                    </button>
                    <ConfirmButton className="btn btn-ghost px-2.5 py-1 text-xs text-red-300" confirmText={tr("Забыть?")}
                                   onConfirm={() => act(() => api(`/users/${id}/devices/${d.id}`, { method: 'DELETE' }), tr("Устройство удалено"))}>
                      <Trash2 size={13} />
                    </ConfirmButton>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-[auto_1fr]">
          <div className="flex flex-col items-center gap-3">
            <div className="rounded-2xl bg-white p-3"><QRCodeSVG value={qrValue} size={180} /></div>
            <select className="input text-xs" value={qr} onChange={(e) => setQr(e.target.value)}>
              <option value="sub">{tr("Умная ссылка (все ключи)")}</option>
              {u.links.map((l) => <option key={l.key} value={l.key}>{l.kind === 'node' ? l.via : l.via ? `📱 ${l.via}` : tr("🏠 напрямую")} · {l.protocol}</option>)}
            </select>
          </div>
          <div className="min-w-0 space-y-3">
            <div>
              <div className="label">{tr("Полная ссылка-подписка (Happ, v2RayTun, Hiddify, Streisand)")}</div>
              <div className="flex gap-2">
                <input className="input font-mono text-xs" readOnly value={u.sub_url} onFocus={(e) => e.target.select()} />
                <CopyButton text={u.sub_url} />
              </div>
            </div>
            {[...new Set(u.links.map((l) => l.via))].map((via) => {
              const group = u.links.filter((l) => l.via === via)
              const kind = group[0].kind
              const relay = kind === 'relay'
              const color = kind === 'relay' ? 'border-amber-500/40 bg-amber-500/5' : kind === 'node' ? 'border-violet-500/40 bg-violet-500/5' : 'border-sky-500/30 bg-sky-500/5'
              return (
                <div key={via} className={`space-y-3 rounded-2xl border p-3 ${color}`}>
                  <div>
                    <div className={`flex flex-wrap items-center gap-2 font-semibold ${relay ? 'text-amber-300' : kind === 'node' ? 'text-violet-300' : 'text-sky-300'}`}>
                      {relay ? tr("📱 Для мобильного интернета — через {0}", via) : kind === 'node' ? tr("{0} — сервер кластера", via) : tr("🏠 Для Wi-Fi и домашнего интернета — напрямую")}
                    </div>
                    <div className="mt-0.5 text-xs text-muted">
                      {relay
                        ? <>{tr("Маршрут: устройство →")}{' '}{via} ({group[0].host}{tr(", Россия) → основной сервер. Используйте, если на мобильном «подключается, но не грузит».")}</>
                        : kind === 'node'
                          ? <>{tr("Маршрут: устройство →")}{' '}{group[0].host}{tr(". Отдельный сервер-выход; трафик и лимиты общие со всем кластером.")}</>
                          : <>{tr("Маршрут: устройство → основной сервер (")}{group[0].host}{tr("). Самый быстрый, если провайдер не режет зарубежные серверы.")}</>}
                    </div>
                  </div>
                  {group.map((l) => (
                    <div key={l.key}>
                      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs">
                        <span className="font-medium text-white">{l.protocol}</span>
                        {l.key.startsWith('steal') && <span className="rounded bg-emerald-500 px-1.5 py-px text-[10px] font-semibold text-black">{tr("🛡 рекомендуется")}</span>}
                        {l.podkop
                          ? <span className="rounded bg-emerald-500/15 px-1.5 py-px text-[10px] text-emerald-300">{tr("подходит для роутера OpenWrt / Podkop")}</span>
                          : <span className="rounded bg-zinc-500/20 px-1.5 py-px text-[10px] text-zinc-400">{tr("только приложения на Xray (не Podkop)")}</span>}
                      </div>
                      <div className="flex gap-2">
                        <input className="input font-mono text-xs" readOnly value={l.url} onFocus={(e) => e.target.select()} />
                        <CopyButton text={l.url} />
                      </div>
                      <div className="mt-1 text-[11px] text-muted">{tr("В приложении:")}{' '}<span className="text-zinc-300">{l.name}</span></div>
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        </div>

        <div className="rounded-2xl bg-panel-2 p-4">
          <div className="mb-2 flex justify-between text-sm">
            <span>{tr("Использовано")}{' '}{bytes(u.used)} <span className="text-muted">(↓ {bytes(u.used_down)} · ↑ {bytes(u.used_up)})</span></span>
            <span className="text-muted">{u.data_limit ? tr("из {0}", bytes(u.data_limit)) : tr("без лимита")}</span>
          </div>
          <Progress value={u.used} max={u.data_limit} />
          <ResponsiveContainer height={90} className="mt-3">
            <BarChart data={u.daily}>
              <XAxis dataKey="day" hide />
              <Tooltip contentStyle={{ background: '#121826', border: '1px solid #232d42', borderRadius: 12, fontSize: 12 }}
                       cursor={{ fill: '#ffffff08' }} formatter={(v: number, n) => [bytes(v), n === 'down' ? tr("Скачано") : tr("Отдано")]} />
              <Bar dataKey="down" stackId="a" fill="#7c6cff" />
              <Bar dataKey="up" stackId="a" fill="#22d3ee" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="grid gap-3 sm:grid-cols-4">
          <div>
            <label className="label">{tr("Лимит, ГБ (0 = ∞)")}</label>
            <input className="input" type="number" min="0" step="any" value={limit} onChange={(e) => setLimit(e.target.value)} />
          </div>
          <div>
            <label className="label">{tr("Действует до (пусто = ∞)")}</label>
            <input className="input" type="date" value={expire} onChange={(e) => setExpire(e.target.value)} />
          </div>
          <div>
            <label className="label">{tr("Заметка")}</label>
            <input className="input" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <div>
            <label className="label">{tr("Скорость, Мбит/с (0 = без ограничения)")}</label>
            <input className="input" type="number" min="0" value={speed} onChange={(e) => setSpeed(e.target.value)} />
          </div>
          <div className="sm:col-span-4">
            <label className="label">{tr("Telegram ID клиента — для уведомлений (клиент пишет боту /start и получает ID)")}</label>
            <div className="flex flex-wrap gap-2">
              <input className="input flex-1 min-w-40 font-mono" inputMode="numeric" placeholder={tr("например 123456789")}
                     value={tgId} onChange={(e) => setTgId(e.target.value)} />
              <button className="btn btn-ghost" disabled={!u.tg_id}
                      title={u.tg_id ? '' : tr("Сначала сохраните Telegram ID")}
                      onClick={() => act(() => api(`/users/${id}/telegram-test`, { method: 'POST' }), tr("Тест отправлен в Telegram"))
                        .catch((e) => { setMsg(e.message); setTimeout(() => setMsg(''), 5000) })}>
                <Send size={15} />{tr("Отправить тест")}
              </button>
              <button className="btn btn-ghost" disabled={!u.tg_id}
                      onClick={() => act(() => api(`/users/${id}/send-sub`, { method: 'POST' }), tr("Подписка отправлена в Telegram"))
                        .catch((e) => { setMsg(e.message); setTimeout(() => setMsg(''), 5000) })}>
                {tr("📲 Отправить подписку")}
              </button>
            </div>
            {u.invite_link ? (
              <div className="mt-2">
                <label className="label">{tr("Приглашение в бота — отправьте клиенту: он нажмёт, бот привяжется и пришлёт подписку сам")}</label>
                <div className="flex gap-2">
                  <input className="input font-mono text-xs" readOnly value={u.invite_link} onFocus={(e) => e.target.select()} />
                  <CopyButton text={u.invite_link} />
                </div>
              </div>
            ) : <div className="mt-1 text-xs text-muted">{tr("Ссылка-приглашение появится, когда подключите бота (раздел Telegram).")}</div>}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <button className="btn btn-primary" onClick={save}>{tr("Сохранить")}</button>
          <button className="btn btn-ghost" onClick={() => act(() => api(`/users/${id}/reset-traffic`, { method: 'POST' }), tr("Трафик сброшен"))}>
            <RefreshCcw size={16} />{tr("Сбросить трафик")}
          </button>
          <ConfirmButton className="btn btn-ghost" confirmText={tr("Ещё раз — старые ссылки перестанут работать")}
                         onConfirm={() => act(() => api(`/users/${id}/regenerate`, { method: 'POST' }), tr("Ключи обновлены"))}>
            <KeyRound size={16} />{tr("Новые ключи")}
          </ConfirmButton>
        </div>
      </div>
    </Modal>
  )
}
