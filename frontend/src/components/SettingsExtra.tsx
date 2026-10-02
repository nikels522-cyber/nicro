import { useEffect, useState } from 'react'
import { Globe, Radar, RefreshCw } from 'lucide-react'
import { api } from '../api'
import { tr } from '../i18n'

type Msg = { ok: boolean; text: string } | null
const Notice = ({ m }: { m: Msg }) => m && <div className={`rounded-xl px-3 py-2 text-sm ${m.ok ? 'bg-emerald-500/10 text-emerald-300' : 'bg-red-500/10 text-red-300'}`}>{m.text}</div>

export function DomainsCard({ panelDomain, subBase, regru, onSave }: {
  panelDomain: string; subBase: string; regru: { username: string; password: string }
  onSave: (patch: object) => Promise<void>
}) {
  const [d, setD] = useState(panelDomain)
  const [r, setR] = useState(regru)
  const [msg, setMsg] = useState<Msg>(null)
  const port = (() => { try { return new URL(subBase).port || '2053' } catch { return '2053' } })()
  const run = (p: object, ok: string) => onSave(p).then(() => setMsg({ ok: true, text: ok })).catch((e) => setMsg({ ok: false, text: e.message }))
  return (
    <section className="card space-y-4">
      <div className="flex items-center gap-2 font-medium"><Globe size={18} className="text-accent" />{tr("Свой домен и DNS")}</div>
      <div>
        <label className="label">{tr("Домен панели и подписок (A-запись → IP главного сервера)")}</label>
        <div className="flex flex-wrap gap-2">
          <input className="input flex-1 min-w-48 font-mono" value={d} onChange={(e) => setD(e.target.value)} placeholder="panel.example.com" />
          <button className="btn btn-primary" onClick={() => run({ panel_domain: d.trim() }, tr("Сохранено. Caddy получит сертификат за 1–2 минуты."))}>{tr("Сохранить")}</button>
        </div>
        <div className="mt-1 text-xs text-muted">
          {tr("Панель будет открываться по https://")}{d || tr("ваш-домен")}:{port}{tr("/…, старый адрес sslip.io тоже продолжит работать. Когда новый адрес откроется — смените «Базовый URL подписок» ниже на https://")}{d || tr("ваш-домен")}:{port}{tr(", тогда при переезде на другой сервер ссылки клиентов не изменятся.")}
        </div>
        {d && <button className="btn btn-ghost mt-2 text-xs" onClick={() => run({ sub_base_url: `https://${d}:${port}` }, tr("Подписки теперь выдаются на вашем домене"))}>{tr("Перевести подписки на")}{' '}{d}</button>}
      </div>
      <div className="rounded-xl bg-panel-2 p-3 space-y-2">
        <div className="text-sm font-medium">{tr("Доступ к API reg.ru (необязательно)")}</div>
        <div className="text-xs text-muted">{tr("Если у точки входа (Pi) сменится IP, панель сама обновит её A-запись. В reg.ru: Настройки → API → разрешите доступ с IP главного сервера и задайте альтернативный пароль API.")}</div>
        <div className="flex flex-wrap gap-2">
          <input className="input w-48" placeholder={tr("логин reg.ru")} value={r.username} onChange={(e) => setR({ ...r, username: e.target.value })} />
          <input className="input w-48" type="password" placeholder={tr("пароль API")} value={r.password} onChange={(e) => setR({ ...r, password: e.target.value })} />
          <button className="btn btn-ghost" onClick={() => run({ regru: r }, tr("Доступ к reg.ru сохранён"))}>{tr("Сохранить")}</button>
        </div>
      </div>
      <Notice m={msg} />
    </section>
  )
}

type Versions = { master: string; nodes: { name: string; xray: string }[]; latest: string | null }

export function UpdatesCard() {
  const [v, setV] = useState<Versions | null>(null)
  const [msg, setMsg] = useState<Msg>(null)
  useEffect(() => { api<Versions>('/xray/versions').then(setV) }, [])
  if (!v) return null
  const cur = v.master.match(/Xray (\S+)/)?.[1]
  const outdated = v.latest && cur && `v${cur}` !== v.latest
  return (
    <section className="card space-y-3">
      <div className="flex items-center gap-2 font-medium"><RefreshCw size={18} className="text-accent" />{tr("Обновление Xray")}</div>
      <div className="text-sm">
        {tr("Главный сервер:")}{' '}<b>{cur ?? '?'}</b>{' '}{tr("· последняя версия:")}{' '}<b>{v.latest ?? '?'}</b> {outdated ? <span className="text-amber-300">{tr("— есть обновление")}</span> : <span className="text-emerald-300">{tr("— актуально")}</span>}
        {v.nodes.map((n) => <div key={n.name} className="text-muted">{n.name}: {n.xray.match(/Xray (\S+)/)?.[1] ?? tr("нет данных")}</div>)}
      </div>
      <button className="btn btn-ghost" onClick={() => api<{ message: string }>('/xray/update', { method: 'POST' }).then((r) => setMsg({ ok: true, text: r.message })).catch((e) => setMsg({ ok: false, text: e.message }))}>
        {tr("Обновить Xray на всех серверах")}
      </button>
      <div className="text-xs text-muted">{tr("На время обновления (≈10 секунд на сервер) соединения клиентов переподключатся.")}</div>
      <Notice m={msg} />
    </section>
  )
}

export function ProbeCard() {
  const [s, setS] = useState<{ enabled: boolean; hide_failed: boolean } | null>(null)
  useEffect(() => { api<{ settings: { enabled: boolean; hide_failed: boolean } }>('/probe').then((p) => setS(p.settings)) }, [])
  if (!s) return null
  const save = (x: typeof s) => api<typeof s>('/probe/settings', { method: 'PUT', body: x }).then(setS)
  return (
    <section className="card space-y-3">
      <div className="flex items-center gap-2 font-medium"><Radar size={18} className="text-accent" />{tr("Проверка ключей из РФ")}</div>
      <div className="text-sm text-muted">{tr("Каждые 10 минут точка входа в РФ (Pi) подключается каждым ключом каждого сервера служебной учёткой и проверяет, что трафик идёт. Результаты — на «Обзоре».")}</div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-emerald-500" checked={s.enabled} onChange={(e) => save({ ...s, enabled: e.target.checked })} />{tr("Проверять")}</label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-emerald-500" checked={s.hide_failed} onChange={(e) => save({ ...s, hide_failed: e.target.checked })} />{tr("Скрывать из подписок ключи, которые не проходят (если не проходит ничего — ничего не скрывается)")}</label>
    </section>
  )
}
