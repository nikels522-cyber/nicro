import { useEffect, useState } from 'react'
import { Plus, Save, Tags, Trash2 } from 'lucide-react'
import { api, type Plan } from '../api'
import { ConfirmButton } from './UserDetail'
import { tr } from '../i18n'

const EMPTY: Omit<Plan, 'id'> = { name: '', days: 30, data_limit_gb: 0, multi_device: true, reset_monthly: false, price: 0, currency: 'RUB', active: true, sort: 0, family_size: 0, speed_mbps: 0 }

function PlanForm({ p, onSave, onDelete }: { p: Plan | null; onSave: (x: Omit<Plan, 'id'>) => Promise<void>; onDelete?: () => void }) {
  const [f, setF] = useState<Omit<Plan, 'id'>>(p ?? EMPTY)
  const [err, setErr] = useState('')
  const set = (k: keyof Plan, v: any) => setF({ ...f, [k]: v })
  return (
    <div className="card space-y-3">
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="sm:col-span-2"><label className="label">{tr("Название")}</label><input className="input" value={f.name} onChange={(e) => set('name', e.target.value)} placeholder={tr("1 месяц · 50 ГБ")} /></div>
        <div><label className="label">{tr("Дней (0 = ∞)")}</label><input className="input" type="number" min={0} value={f.days} onChange={(e) => set('days', Number(e.target.value))} /></div>
        <div><label className="label">{tr("Трафик, ГБ (0 = ∞)")}</label><input className="input" type="number" min={0} step="any" value={f.data_limit_gb} onChange={(e) => set('data_limit_gb', Number(e.target.value))} /></div>
        <div><label className="label">{tr("Цена")}</label><input className="input" type="number" min={0} step="any" value={f.price} onChange={(e) => set('price', Number(e.target.value))} /></div>
        <div><label className="label">{tr("Валюта")}</label><select className="input" value={f.currency} onChange={(e) => set('currency', e.target.value)}>{['RUB'].map((c) => <option key={c}>{c}</option>)}</select></div>
        <div><label className="label">{tr("Семья: + участников")}</label><input className="input" type="number" min={0} value={f.family_size} onChange={(e) => set('family_size', Number(e.target.value))} /></div>
        <div><label className="label">{tr("Скорость, Мбит/с (0 = ∞)")}</label><input className="input" type="number" min={0} value={f.speed_mbps} onChange={(e) => set('speed_mbps', Number(e.target.value))} /></div>
        <div><label className="label">{tr("Порядок")}</label><input className="input" type="number" value={f.sort} onChange={(e) => set('sort', Number(e.target.value))} /></div>
      </div>
      <div className="flex flex-wrap gap-4 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-emerald-500" checked={f.multi_device} onChange={(e) => set('multi_device', e.target.checked)} />{tr("Мультиаккаунт")}</label>
        <label className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-emerald-500" checked={f.reset_monthly} onChange={(e) => set('reset_monthly', e.target.checked)} />{tr("Сброс трафика каждые 30 дней")}</label>
        <label className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-emerald-500" checked={f.active} onChange={(e) => set('active', e.target.checked)} />{tr("Активен")}</label>
      </div>
      {err && <div className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</div>}
      <div className="flex gap-2">
        <button className="btn btn-primary" onClick={() => onSave(f).catch((e) => setErr(e.message))}><Save size={16} />{tr("Сохранить")}</button>
        {onDelete && <ConfirmButton className="btn btn-danger sm:ml-auto" confirmText={tr("Удалить тариф?")} onConfirm={onDelete}><Trash2 size={16} />{tr("Удалить")}</ConfirmButton>}
      </div>
    </div>
  )
}

export default function Plans({ canEdit }: { canEdit: boolean }) {
  const [plans, setPlans] = useState<Plan[]>([])
  const [adding, setAdding] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const load = () => api<Plan[]>('/plans').then(setPlans)
  useEffect(() => { load() }, [])

  return (
    <div className="max-w-4xl space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold"><Tags size={22} className="text-accent" />{tr("Тарифы")}</h1>
          <p className="text-sm text-muted">{tr("Шаблоны для создания и продления клиентов в одно нажатие. Тарифы с ценой продаются в боте и на странице клиента, когда подключена онлайн-оплата (Дополнения → Онлайн-оплата).")}</p>
        </div>
        {canEdit && <button className="btn btn-primary" onClick={() => setAdding(true)}><Plus size={18} />{tr("Новый тариф")}</button>}
      </header>
      {adding && <PlanForm p={null} onSave={async (x) => { await api('/plans', { body: x }); setAdding(false); load() }} />}
      {plans.length === 0 && !adding && <div className="card text-sm text-muted">{tr("Тарифов пока нет. Создайте, например: «1 месяц · 50 ГБ · 1 устройство».")}</div>}
      {plans.map((p) => editId === p.id ? (
        <PlanForm key={p.id} p={p} onSave={async (x) => { await api(`/plans/${p.id}`, { method: 'PATCH', body: x }); setEditId(null); load() }}
                  onDelete={async () => { await api(`/plans/${p.id}`, { method: 'DELETE' }); setEditId(null); load() }} />
      ) : (
        <div key={p.id} className={`card flex flex-wrap items-center gap-4 ${p.active ? '' : 'opacity-50'}`}>
          <div className="min-w-0 flex-1">
            <div className="font-medium">{p.name} {!p.active && <span className="text-xs text-muted">{tr("(скрыт)")}</span>}</div>
            <div className="text-sm text-muted">
              {p.days ? tr("{0} дн.", p.days) : tr("бессрочно")} · {p.data_limit_gb ? tr("{0} ГБ", p.data_limit_gb) : tr("безлимит")}
              {p.reset_monthly && tr(" (каждые 30 дн.)")} · {p.multi_device ? tr("много устройств") : tr("1 устройство")}
              {p.family_size > 0 && tr(" · семья до {0}", p.family_size + 1)}{p.speed_mbps > 0 && tr(" · {0} Мбит/с", p.speed_mbps)}
            </div>
          </div>
          <div className="text-lg font-semibold tabular-nums">{p.price ? `${p.price} ${p.currency}` : tr("бесплатно")}</div>
          {canEdit && <button className="btn btn-ghost" onClick={() => setEditId(p.id)}>{tr("Изменить")}</button>}
        </div>
      ))}
    </div>
  )
}
