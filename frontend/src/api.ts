import { tr } from './i18n'
// The panel lives under a secret path (e.g. /x7f3k/), API is at <path>/api
const root = location.pathname.replace(/\/+$/, '').replace(/\/index\.html$/, '') || '/panel'
export const API = `${root}/api`

let token = localStorage.getItem('token') || ''
export const getToken = () => token
export function setToken(t: string) {
  token = t
  t ? localStorage.setItem('token', t) : localStorage.removeItem('token')
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(API + path, {
    method: opts.method || (opts.body ? 'POST' : 'GET'),
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  })
  if (res.status === 401 && path !== '/auth/login') {
    setToken('')
    location.reload()
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : tr("Ошибка запроса")
    throw new ApiError(res.status, tr(detail))  // server messages are Russian: translated like the UI
  }
  return data
}

export function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${API}/ws?token=${encodeURIComponent(token)}`
}

export type User = {
  id: number; username: string; status: 'active' | 'disabled' | 'expired' | 'limited'; enabled: boolean
  data_limit: number; used_up: number; used_down: number; used: number
  expire_at: number | null; created_at: number; last_online: number | null; online: boolean; note: string
  multi_device: boolean
  devices_online: number
  tg_id: string
  plan_id: number | null
  reset_monthly: boolean
  l2tp_enabled: boolean
  parent_id: number | null
  speed_mbps: number
  referred_by: number | null
  pending_signup: boolean
  hide_ip: boolean
  smart_link?: string
}

export type UserDetail = User & {
  links: { protocol: string; key: string; url: string; via: string; kind: 'relay' | 'direct' | 'node'; host: string; podkop: boolean; name: string }[]
  sub_url: string
  invite_link: string | null
  smart_link: string
  l2tp: { server: string; psk: string; login: string; password: string; online: boolean } | null
  family: { parent: { id: number; username: string } | null; members: User[]; limit: number | null }
  referral: { invited: { id: number; username: string; paid: boolean }[]; invited_by: { id: number; username: string } | null; link: string | null }
  promo: { code: string; value: number } | null
  daily: { day: string; up: number; down: number }[]
  devices: {
    id: number | null; kind: 'device' | 'ip'; name: string; os: string; app: string; enabled: boolean
    online: boolean; blocked: boolean; ips: string[]; last_seen: number | null; created_at: number | null
  }[]
}

export type Metrics = {
  ts: number; cpu: number; cpu_cores: number[]; cpu_count: number; load: number[]
  mem_used: number; mem_total: number; swap_used: number; swap_total: number
  disk_used: number; disk_total: number; net_rx_rate: number; net_tx_rate: number
  net_rx_total: number; net_tx_total: number; tcp: number; uptime: number
}

export type SystemPayload = {
  metrics: Metrics
  users: { total: number; active: number; disabled: number; expired: number; limited: number; online: number }
  traffic_total: number
  services: Record<string, string>
  hy_online: Record<string, number>
  relays: RelayStatus[]
}

export type Role = 'owner' | 'operator' | 'support' | 'viewer'
export type Me = { username: string; role: Role; totp_enabled: boolean; tg_id: string }
export const ROLE_NAMES: Record<Role, string> = { owner: tr("Владелец"), operator: tr("Оператор"), support: tr("Поддержка"), viewer: tr("Наблюдатель") }

export type Plan = {
  id: number; name: string; days: number; data_limit_gb: number; multi_device: boolean; reset_monthly: boolean
  price: number; currency: string; active: boolean; sort: number; family_size: number; speed_mbps: number
}

export type Provider = {
  name: string; title: string; hint: string; enabled: boolean; ready: boolean; webhook: string
  fields: { key: string; label: string; secret: boolean; value: string }[]
}
export type PaymentsSettings = { providers: Provider[]; return_url: string }

export type RelayStatus = {
  name: string; host: string; online: boolean; error: string | null; rtt_ms?: number
  checked_at: number; last_seen?: number
  metrics?: {
    model: string; hostname: string; cpu: number; cpu_count: number; load: number[]
    mem_total: number; mem_used: number; disk_total: number; disk_used: number; temp: number | null
    uptime: number; net_rx_rate: number; net_tx_rate: number; net_rx_total: number; net_tx_total: number
    connections: number; throttled: string | null
  }
}
