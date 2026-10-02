import { useEffect, useState } from 'react'
import { Cloud, Plus, Trash2 } from 'lucide-react'
import { api } from '../api'
import { Switch } from './brand'
import { tr } from '../i18n'

type Field = { key: string; label: string; secret: boolean }
type Kind = { type: string; title: string; fields: Field[]; help: string }
type Item = { id?: string; type: string; name: string; enabled: boolean; path: string; params: Record<string, string> }

export default function Storages() {
  const [catalog, setCatalog] = useState<Kind[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [msg, setMsg] = useState<Record<string, string>>({})
  const [adding, setAdding] = useState('')
  const load = () => api<{ catalog: Kind[]; items: Item[] }>('/backups/storages').then((r) => { setCatalog(r.catalog); setItems(r.items) })
  useEffect(() => { load() }, [])

  const save = async (next: Item[]) => { const r = await api<{ items: Item[] }>('/backups/storages', { method: 'PUT', body: { items: next } }); setItems(r.items) }
  const kind = (t: string) => catalog.find((c) => c.type === t)

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium"><Cloud size={16} className="text-accent-2" />{tr("Облачные хранилища — каждый бэкап копируется во все включённые")}</div>
      {items.map((it, i) => {
        const k = kind(it.type)
        return (
          <div key={it.id} className="space-y-2 rounded-xl border border-line bg-bg/40 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Switch on={it.enabled} onChange={(v) => save(items.map((x, j) => (j === i ? { ...x, enabled: v } : x)))} />
              <b className="text-sm">{it.name}</b><span className="text-xs text-muted">{k?.title}{' '}{tr("· папка")}{' '}{it.path}</span>
              <button className="btn btn-ghost ml-auto px-2.5 py-1 text-xs"
                      onClick={async () => { setMsg({ ...msg, [it.id!]: tr("Проверяю…") }); const r = await api<{ ok: boolean; error?: string }>(`/backups/storages/${it.id}/test`, { method: 'POST' }); setMsg({ ...msg, [it.id!]: r.ok ? tr("✅ Подключение работает") : `❌ ${r.error}` }) }}>
                {tr("Проверить")}
              </button>
              <button className="btn btn-ghost px-2.5 py-1 text-xs text-red-300" onClick={() => save(items.filter((_, j) => j !== i))}><Trash2 size={13} /></button>
            </div>
            {msg[it.id!] && <div className="break-all text-xs text-muted">{msg[it.id!]}</div>}
          </div>
        )
      })}
      {adding ? <NewStorage kind={kind(adding)!} onCancel={() => setAdding('')} onSave={async (it) => { await save([...items, it]); setAdding('') }} /> : (
        <div className="flex flex-wrap gap-2">
          {catalog.map((c) => <button key={c.type} className="btn btn-ghost py-1.5 text-xs" onClick={() => setAdding(c.type)}><Plus size={13} />{c.title}</button>)}
        </div>
      )}
    </div>
  )
}

function NewStorage({ kind, onSave, onCancel }: { kind: Kind; onSave: (it: Item) => Promise<void>; onCancel: () => void }) {
  const [it, setIt] = useState<Item>({ type: kind.type, name: kind.title, enabled: true, path: 'nicro-backups', params: {} })
  const [err, setErr] = useState('')
  return (
    <div className="space-y-3 rounded-xl border border-accent/40 bg-accent/5 p-3">
      <div className="text-sm font-medium">{kind.title}</div>
      {kind.help && <div className="text-xs text-muted">{kind.help}</div>}
      <div className="grid gap-2 sm:grid-cols-2">
        {kind.fields.map((f) => (
          <div key={f.key} className={f.key === 'token' ? 'sm:col-span-2' : ''}>
            <label className="label">{f.label}</label>
            {f.key === 'token'
              ? <textarea className="input h-20 font-mono text-xs" value={it.params[f.key] ?? ''} onChange={(e) => setIt({ ...it, params: { ...it.params, [f.key]: e.target.value } })} />
              : <input className="input" type={f.secret ? 'password' : 'text'} value={it.params[f.key] ?? ''} onChange={(e) => setIt({ ...it, params: { ...it.params, [f.key]: e.target.value } })} />}
          </div>
        ))}
        <div><label className="label">{tr("Папка")}{kind.type === 's3' ? tr(" (бакет/путь)") : ''}</label><input className="input" value={it.path} onChange={(e) => setIt({ ...it, path: e.target.value })} /></div>
        <div><label className="label">{tr("Название")}</label><input className="input" value={it.name} onChange={(e) => setIt({ ...it, name: e.target.value })} /></div>
      </div>
      {err && <div className="text-sm text-red-300">{err}</div>}
      <div className="flex gap-2"><button className="btn btn-primary" onClick={() => onSave(it).catch((e) => setErr(e.message))}>{tr("Добавить")}</button><button className="btn btn-ghost" onClick={onCancel}>{tr("Отмена")}</button></div>
    </div>
  )
}
