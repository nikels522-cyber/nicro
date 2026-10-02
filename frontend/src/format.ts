import { LOCALE, tr } from './i18n'
export function bytes(n: number, digits = 1): string {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1)
  return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : digits)} ${u[i]}`
}

export const rate = (n: number) => `${bytes(n)}/s`

export function duration(sec: number): string {
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60)
  return d ? tr("{0}д {1}ч", d, h) : h ? tr("{0}ч {1}м", h, m) : tr("{0}м", m)
}

export function date(ts: number | null): string {
  return ts ? new Date(ts * 1000).toLocaleDateString(LOCALE, { day: '2-digit', month: 'short', year: 'numeric' }) : '—'
}

export function relative(ts: number | null): string {
  if (!ts) return tr("никогда")
  const diff = Date.now() / 1000 - ts
  if (diff < 60) return tr("только что")
  if (diff < 3600) return tr("{0} мин назад", Math.floor(diff / 60))
  if (diff < 86400) return tr("{0} ч назад", Math.floor(diff / 3600))
  return tr("{0} дн назад", Math.floor(diff / 86400))
}

export function daysLeft(ts: number | null): string {
  if (!ts) return '∞'
  const d = Math.ceil((ts * 1000 - Date.now()) / 86400000)
  return d > 0 ? tr("{0} дн", d) : tr("истёк")
}
