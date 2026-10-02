import { useEffect, useState } from 'react'
import { Check, Copy, Download, KeyRound, Plus, ShieldCheck, Terminal, Trash2 } from 'lucide-react'
import { api } from '../api'
import { relative } from '../format'
import { ConfirmButton } from './UserDetail'
import { AdminsCard, AuditCard, MyAccountCard } from '../components/SecurityCards'
import { tr } from '../i18n'

type Fw = {
  enabled: boolean; via_vpn: boolean; allow: { cidr: string; note: string }[]
  your_ip: string; server_ip: string; active: boolean; denied: { ip: string; ts: number; path: string }[]
}
type Ssh = { enabled: boolean; password: boolean; port: number; user?: string; keys: { type: string; fingerprint: string; name: string; from_panel: boolean }[] }

function Switch({ on, onChange, disabled }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button type="button" disabled={disabled} onClick={() => onChange(!on)}
            className={`relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-50 ${on ? 'bg-accent' : 'bg-zinc-600'}`}>
      <span className={`absolute top-0.5 size-5 rounded-full bg-white transition-all ${on ? 'left-5.5' : 'left-0.5'}`} />
    </button>
  )
}

function Notice({ m }: { m: { ok: boolean; text: string } | null }) {
  if (!m) return null
  return <div className={`rounded-xl px-3 py-2 text-sm ${m.ok ? 'bg-emerald-500/10 text-emerald-300' : 'bg-red-500/10 text-red-300'}`}>{m.text}</div>
}

function FirewallCard() {
  const [fw, setFw] = useState<Fw | null>(null)
  const [draft, setDraft] = useState<Fw | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const load = () => api<Fw>('/firewall').then((f) => { setFw(f); setDraft(f) })
  useEffect(() => { load() }, [])
  if (!fw || !draft) return <div className="card text-muted">{tr("Загрузка…")}</div>

  const upd = (i: number, k: 'cidr' | 'note', v: string) => setDraft({ ...draft, allow: draft.allow.map((r, j) => (j === i ? { ...r, [k]: v } : r)) })
  const hasMine = draft.allow.some((r) => r.cidr === fw.your_ip)

  async function save() {
    setMsg(null)
    try {
      const r = await api<Fw>('/firewall', { method: 'PUT', body: { enabled: draft!.enabled, via_vpn: draft!.via_vpn, allow: draft!.allow.filter((x) => x.cidr.trim()) } })
      setFw(r); setDraft(r)
      setMsg({ ok: true, text: r.active ? tr("Сохранено. Панель доступна только с разрешённых адресов.") : tr("Сохранено. Файрвол выключен — панель доступна отовсюду.") })
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
  }

  return (
    <section className="card space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 font-medium"><ShieldCheck size={20} className="text-accent" />{tr("Доступ к панели (файрвол)")}</div>
        <span className={`rounded-full px-3 py-1 text-xs ${fw.active ? 'bg-emerald-500/15 text-emerald-300' : 'bg-zinc-500/20 text-zinc-400'}`}>
          {fw.active ? tr("● включён") : tr("выключен — доступ отовсюду")}
        </span>
      </div>
      <p className="text-sm text-muted">
        {tr("Панель открывается только с перечисленных адресов. С остальных — «не найдено», будто панели нет. Подписки клиентов работают для всех как обычно. Ваш текущий IP:")}{' '}<b className="font-mono text-white">{fw.your_ip}</b>
      </p>

      <label className="flex items-center gap-3 rounded-xl bg-panel-2 px-3 py-2.5">
        <Switch on={draft.enabled} onChange={(v) => setDraft({ ...draft, enabled: v })} />
        <span className="text-sm font-medium">{tr("Включить файрвол")}</span>
      </label>
      <label className="flex items-start gap-3 rounded-xl bg-panel-2 px-3 py-2.5">
        <Switch on={draft.via_vpn} onChange={(v) => setDraft({ ...draft, via_vpn: v })} />
        <span className="text-sm">
          <span className="block font-medium">{tr("Разрешить через наш VPN")}</span>
          <span className="block text-xs text-muted">{tr("С включённым VPN вы заходите с адреса сервера (")}{fw.server_ip}{tr(") — удобно с телефона на мобильном интернете, где IP всё время меняется.")}</span>
        </span>
      </label>

      <div className="space-y-2">
        <div className="label">{tr("Разрешённые адреса и диапазоны (например 203.0.113.7 или 10.145.0.0/16)")}</div>
        {draft.allow.map((r, i) => (
          <div key={i} className="flex flex-wrap gap-2">
            <input className="input flex-[2] min-w-40 font-mono" value={r.cidr} placeholder={tr("IP или IP/маска")} onChange={(e) => upd(i, 'cidr', e.target.value)} />
            <input className="input flex-[2] min-w-32" value={r.note} placeholder={tr("комментарий: дом, офис…")} onChange={(e) => upd(i, 'note', e.target.value)} />
            <button className="btn btn-ghost px-2.5" title={tr("Удалить")} onClick={() => setDraft({ ...draft, allow: draft.allow.filter((_, j) => j !== i) })}><Trash2 size={16} /></button>
          </div>
        ))}
        <div className="flex flex-wrap gap-2">
          {!hasMine && <button className="btn btn-ghost" onClick={() => setDraft({ ...draft, allow: [...draft.allow, { cidr: fw.your_ip, note: tr("мой IP") }] })}><Plus size={16} />{tr("Добавить мой текущий IP")}</button>}
          <button className="btn btn-ghost" onClick={() => setDraft({ ...draft, allow: [...draft.allow, { cidr: '', note: '' }] })}><Plus size={16} />{tr("Добавить адрес")}</button>
          <button className="btn btn-primary" onClick={save}>{tr("Сохранить")}</button>
        </div>
      </div>
      <Notice m={msg} />

      {fw.denied.length > 0 && (
        <div className="rounded-xl bg-panel-2 p-3">
          <div className="mb-1.5 text-xs font-medium text-muted">{tr("Последние заблокированные попытки")}</div>
          {fw.denied.slice(0, 10).map((d, i) => (
            <div key={i} className="flex justify-between text-xs"><span className="font-mono text-red-300">{d.ip}</span><span className="text-muted">{relative(d.ts)}</span></div>
          ))}
        </div>
      )}
      <div className="text-xs text-muted">
        {tr("Если заблокировали себя: по SSH на сервере выполните")}{' '}
        <code className="text-zinc-300">cd /opt/vpnpanel &amp;&amp; set -a &amp;&amp; . /etc/vpnpanel.env &amp;&amp; venv/bin/python -m app.cli firewall off &amp;&amp; systemctl restart vpnpanel</code>
      </div>
    </section>
  )
}

type SshServer = { id: string; name: string; kind: 'main' | 'relay' | 'node'; host: string }
const KIND_NAME = { main: tr("основной"), relay: tr("точка входа"), node: tr("узел-выход") }

export function SshCard({ initial = 'main', bare = false }: { initial?: string; bare?: boolean }) {
  const [servers, setServers] = useState<SshServer[]>([])
  const [srv, setSrv] = useState(initial)
  const [st, setSt] = useState<Ssh | null>(null)
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [name, setName] = useState('admin')
  const [newKey, setNewKey] = useState<{ private_key: string; fingerprint: string; user?: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const q = `?server=${encodeURIComponent(srv)}`
  const load = () => {
    setLoading(true); setMsg(null)
    return api<Ssh>('/ssh' + q).then(setSt).catch((e) => { setSt(null); setMsg({ ok: false, text: e.message }) }).finally(() => setLoading(false))
  }
  useEffect(() => { api<SshServer[]>('/ssh/servers').then(setServers).catch(() => {}) }, [])
  useEffect(() => { setNewKey(null); load() }, [srv])
  const server = servers.find((x) => x.id === srv)

  async function put(body: object, ok: string) {
    setMsg(null)
    try { setSt(await api<Ssh>('/ssh' + q, { method: 'PUT', body })); setMsg({ ok: true, text: ok }) } catch (e: any) { setMsg({ ok: false, text: e.message }) }
  }
  async function gen() {
    setMsg(null)
    try {
      const k = await api<{ private_key: string; fingerprint: string; user?: string }>('/ssh/keys' + q, { body: { name } })
      setNewKey(k); load()
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([newKey!.private_key], { type: 'text/plain' }))
    const a = document.createElement('a'); a.href = url; a.download = `vpn-server-${name || 'admin'}.key`; a.click()
    URL.revokeObjectURL(url)
  }

  const host = server?.kind === 'main' || !server
    ? location.hostname.replace(/^(\d+)-(\d+)-(\d+)-(\d+)\.sslip\.io$/, '$1.$2.$3.$4') : server.host
  return (
    <section className={bare ? 'space-y-4' : 'card space-y-4'}>
      {!bare && <div className="flex items-center gap-2 font-medium"><Terminal size={20} className="text-accent" />{tr("SSH-доступ к серверам")}</div>}
      {servers.length > 1 && (
        <div className="flex flex-wrap gap-1 rounded-xl border border-line bg-panel-2/60 p-1">
          {servers.map((x) => (
            <button key={x.id} onClick={() => setSrv(x.id)}
                    className={`rounded-lg px-3 py-1.5 text-sm transition ${srv === x.id ? 'bg-accent text-white' : 'text-muted hover:text-white'}`}>
              {tr(x.name)} <span className="text-[11px] opacity-70">· {KIND_NAME[x.kind]}</span>
            </button>
          ))}
        </div>
      )}
      {loading && <div className="text-sm text-muted">{tr("Связываюсь с сервером…")}</div>}
      {!loading && !st && <Notice m={msg} />}
      {!loading && st && <>

      <div className="flex items-start gap-3 rounded-xl bg-panel-2 px-3 py-2.5">
        <Switch on={st.enabled} onChange={(v) => put({ enabled: v }, v ? tr("SSH включён") : tr("SSH выключен. Включить обратно можно здесь же."))} />
        <span className="text-sm">
          <span className="block font-medium">SSH {st.enabled ? tr("включён") : tr("выключен")} <span className="font-normal text-muted">{tr("(порт")}{' '}{st.port}{st.user && st.user !== 'root' ? tr(", пользователь {0}", st.user) : ''})</span></span>
          <span className="block text-xs text-muted">{tr("Выключенный SSH полностью закрывает вход в консоль сервера. Панель продолжает работать, и SSH можно включить обратно отсюда.")}</span>
        </span>
      </div>
      <div className="flex items-start gap-3 rounded-xl bg-panel-2 px-3 py-2.5">
        <Switch on={st.password} onChange={(v) => put({ password: v }, v ? tr("Вход по паролю включён") : tr("Вход по паролю выключен — только по ключу"))} />
        <span className="text-sm">
          <span className="block font-medium">{tr("Вход по паролю")}{' '}{st.password ? tr("разрешён") : tr("запрещён")}</span>
          <span className="block text-xs text-muted">{st.password ? tr("Рекомендуется выключить: пароль root побывал в переписке. Сначала создайте ключ.") : tr("Вход только по SSH-ключу — пароли подобрать невозможно.")}</span>
        </span>
      </div>
      <Notice m={msg} />

      <div className="space-y-2">
        <div className="label">{tr("SSH-ключи (кому разрешён вход)")}</div>
        {st.keys.length === 0 && <div className="text-sm text-muted">{tr("Ключей нет.")}</div>}
        {st.keys.map((k) => (
          <div key={k.fingerprint} className="flex flex-wrap items-center gap-3 rounded-xl bg-panel-2 px-3 py-2 text-sm">
            <KeyRound size={16} className="text-accent" />
            <div className="min-w-0 flex-1">
              <div className="font-medium">{k.name || tr("без названия")} {!k.from_panel && <span className="text-xs text-muted">{tr("(добавлен вручную)")}</span>}</div>
              <div className="truncate font-mono text-xs text-muted">{k.type} {k.fingerprint}</div>
            </div>
            <ConfirmButton className="btn btn-ghost px-2.5 py-1 text-xs text-red-300" confirmText={tr("Удалить?")}
                           onConfirm={async () => { try { setSt(await api<Ssh>(`/ssh/keys/${encodeURIComponent(k.fingerprint)}`, { method: 'DELETE' })) } catch (e: any) { setMsg({ ok: false, text: e.message }) } }}>
              <Trash2 size={13} />
            </ConfirmButton>
          </div>
        ))}
        <div className="flex flex-wrap gap-2">
          <input className="input w-48" value={name} onChange={(e) => setName(e.target.value)} placeholder={tr("название: ноутбук, телефон")} />
          <button className="btn btn-primary" onClick={gen}><Plus size={16} />{tr("Сгенерировать ключ")}</button>
        </div>
      </div>

      {newKey && (
        <div className="space-y-3 rounded-2xl border border-amber-500/40 bg-amber-500/5 p-4">
          <div className="font-medium text-amber-300">{tr("⚠️ Сохраните закрытый ключ сейчас — он показывается один раз и на сервере не хранится")}</div>
          <textarea readOnly className="input h-40 font-mono text-[11px]" value={newKey.private_key} onFocus={(e) => e.target.select()} />
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-primary" onClick={download}><Download size={16} />{tr("Скачать файл ключа")}</button>
            <button className="btn btn-ghost" onClick={() => navigator.clipboard.writeText(newKey.private_key).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })}>
              {copied ? <Check size={16} /> : <Copy size={16} />}{tr("Копировать")}
            </button>
            <button className="btn btn-ghost" onClick={() => setNewKey(null)}>{tr("Я сохранил, скрыть")}</button>
          </div>
          <div className="text-xs text-muted space-y-1">
            <div>{tr("Вход с компьютера:")}{' '}<code className="text-zinc-300">{tr("ssh -i путь/к/файлу.key")}{' '}{newKey.user || st.user || 'root'}@{host}</code></div>
            <div>{tr("С телефона: приложение Termius → Keychain → Import key → вставьте ключ.")}</div>
          </div>
        </div>
      )}
      </>}
    </section>
  )
}

export default function Security({ owner }: { owner: boolean }) {
  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold">{tr("Безопасность")}</h1>
      <MyAccountCard />
      {owner && <>
        <AdminsCard />
        <FirewallCard />
        <SshCard />
        <AuditCard />
      </>}
    </div>
  )
}
