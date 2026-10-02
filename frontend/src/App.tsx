import { lazy, Suspense, useEffect, useState } from 'react'
import { Download, LayoutDashboard, LifeBuoy, LogOut, Menu, Smartphone, Puzzle, Server, Settings as SettingsIcon, ShieldCheck, Tags, Users as UsersIcon, X } from 'lucide-react'
import { api, getToken, ROLE_NAMES, setToken, type Me } from './api'
import Login from './pages/Login'
// pages load on first visit: the phone downloads only what it shows
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Users = lazy(() => import('./pages/Users'))
const Settings = lazy(() => import('./pages/Settings'))
const Security = lazy(() => import('./pages/Security'))
const Servers = lazy(() => import('./pages/Servers'))
const Plans = lazy(() => import('./pages/Plans'))
const Extensions = lazy(() => import('./pages/Extensions'))
const Support = lazy(() => import('./pages/Support'))
import { LangSwitch, Logo } from './components/brand'
import { getInstallPrompt, standalone } from './components/install'
const MobileAppModal = lazy(() => import('./components/MobileApp').then((m) => ({ default: m.MobileAppModal })))
import { tr } from './i18n'

const PAGES = [
  { id: 'dashboard', label: tr("Обзор"), icon: LayoutDashboard, group: tr("Главное"), owner: false },
  { id: 'users', label: tr("Клиенты"), icon: UsersIcon, group: tr("Главное"), owner: false },
  { id: 'plans', label: tr("Тарифы"), icon: Tags, group: tr("Главное"), owner: false },
  { id: 'support', label: tr("Поддержка"), icon: LifeBuoy, group: tr("Главное"), owner: false },
  { id: 'servers', label: tr("Серверы"), icon: Server, group: tr("Инфраструктура"), owner: true },
  { id: 'extensions', label: tr("Дополнения"), icon: Puzzle, group: tr("Расширения"), owner: true },
  { id: 'security', label: tr("Безопасность"), icon: ShieldCheck, group: tr("Система"), owner: false },
  { id: 'settings', label: tr("Настройки"), icon: SettingsIcon, group: tr("Система"), owner: true },
] as const
type PageId = (typeof PAGES)[number]['id']
const MOBILE_TABS: PageId[] = ['dashboard', 'users', 'servers', 'extensions']

const pageFromHash = (): PageId => {
  const h = location.hash.replace('#', '')
  if (h === 'telegram') return 'extensions'  // old bookmark
  if (h.startsWith('user/')) return 'users'  // a client's card
  return (PAGES.find((p) => p.id === h)?.id ?? 'dashboard')
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken())
  const [page, setPage] = useState<PageId>(pageFromHash)
  const [me, setMe] = useState<Me | null>(null)
  const [more, setMore] = useState(false)
  const [phone, setPhone] = useState(false)  // "app on the phone" dialog
  const [install, setInstall] = useState<any>(getInstallPrompt)  // Android/Chrome "install app" prompt (PWA)

  useEffect(() => {  // opened from the install QR while already signed in: offer the installation right away
    if (authed && new URLSearchParams(location.search).has('install')) {
      if (!standalone()) setPhone(true)
      history.replaceState(null, '', location.pathname + location.hash)
    }
  }, [authed])
  const [unread, setUnread] = useState(0)  // support messages waiting for an answer
  useEffect(() => { if (authed) api<Me>('/auth/me').then(setMe).catch(() => {}) }, [authed])
  useEffect(() => {
    if (!authed) return
    const poll = () => api<{ unread: number }>('/support/unread').then((r) => setUnread(r.unread)).catch(() => {})
    poll()
    const t = setInterval(poll, 30000)
    return () => clearInterval(t)
  }, [authed, page])
  useEffect(() => {
    const onPrompt = () => setInstall(getInstallPrompt())
    const onHash = () => { setPage(pageFromHash()); setMore(false) }
    addEventListener('nicro-install', onPrompt)
    addEventListener('hashchange', onHash)
    return () => { removeEventListener('nicro-install', onPrompt); removeEventListener('hashchange', onHash) }
  }, [])

  const installApp = async () => { install.prompt(); await install.userChoice; setInstall(null) }
  if (!authed) return <Login onDone={() => setAuthed(true)} install={install ? installApp : undefined} />
  const owner = me?.role === 'owner'
  // the "support" role sees only conversations, clients (read-only) and its own account
  const visible = PAGES.filter((p) => owner || (!p.owner && (me?.role !== 'support' || ['support', 'users', 'security'].includes(p.id))))
  if (me && !visible.some((p) => p.id === page)) setTimeout(() => { location.hash = visible[0]?.id === 'dashboard' ? '#dashboard' : '#support' })
  const groups = [...new Set(visible.map((p) => p.group))]
  const current = PAGES.find((p) => p.id === page)!
  const logout = () => { setToken(''); setAuthed(false) }

  const navLink = (p: (typeof PAGES)[number]) => (
    <a key={p.id} href={`#${p.id}`}
       className={`group flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition ${page === p.id
         ? 'bg-gradient-to-r from-accent/20 to-accent/5 text-white shadow-[inset_2px_0_0_var(--color-accent)]'
         : 'text-muted hover:bg-panel-2 hover:text-white'}`}>
      <p.icon size={18} className={page === p.id ? 'text-accent' : 'text-muted group-hover:text-white'} />{p.label}
      {p.id === 'support' && unread > 0 && <span className="ml-auto rounded-full bg-accent px-1.5 text-[11px] font-bold text-white">{unread}</span>}
    </a>
  )

  return (
    <div className="flex min-h-full">
      {/* desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-line bg-panel/70 px-4 py-6 backdrop-blur md:flex">
        <div className="mb-8 px-2"><Logo /></div>
        <nav className="flex-1 space-y-5 overflow-y-auto">
          {groups.map((g) => (
            <div key={g}>
              <div className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-muted/70">{g}</div>
              <div className="space-y-0.5">{visible.filter((p) => p.group === g).map(navLink)}</div>
            </div>
          ))}
        </nav>
        <LangSwitch className="mb-3" />
        <button className="btn btn-ghost mb-3 w-full" onClick={() => setPhone(true)}><Smartphone size={16} />{tr("Приложение nicro")}</button>
        {install && <button className="btn btn-ghost mb-3 w-full" onClick={installApp}><Download size={16} />{tr("Установить приложение")}</button>}
        <div className="flex items-center gap-3 rounded-2xl border border-line bg-panel-2/60 p-3">
          <div className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-accent to-accent-2 text-sm font-bold text-white">
            {(me?.username ?? '?').slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{me?.username}</div>
            <div className="text-xs text-muted">{me ? ROLE_NAMES[me.role] : ''}</div>
          </div>
          <button title={tr("Выйти")} className="rounded-lg p-1.5 text-muted hover:bg-line hover:text-white" onClick={logout}><LogOut size={16} /></button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* mobile top bar */}
        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-bg/80 px-4 py-3 backdrop-blur md:hidden"
                style={{ paddingTop: 'max(0.75rem, env(safe-area-inset-top))' }}>
          <Logo small />
          <span className="text-sm text-muted">{current.label}</span>
        </header>

        <main className="min-w-0 flex-1 p-4 pb-28 md:p-8 md:pb-8">
          <Suspense fallback={<div className="text-muted">{tr("Загрузка…")}</div>}>
          {page === 'dashboard' && <Dashboard />}
          {page === 'users' && <Users />}
          {page === 'plans' && <Plans canEdit={owner} />}
          {page === 'servers' && <Servers />}
          {page === 'extensions' && <Extensions />}
          {page === 'security' && <Security owner={owner} />}
          {page === 'settings' && <Settings />}
          {page === 'support' && <Support owner={owner} />}
          </Suspense>
        </main>
      </div>

      {/* mobile bottom tabs */}
      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-line bg-panel/95 backdrop-blur md:hidden"
           style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}>
        {MOBILE_TABS.map((id) => PAGES.find((p) => p.id === id)!).filter((p) => visible.includes(p)).map((p) => (
          <a key={p.id} href={`#${p.id}`} className={`flex flex-col items-center gap-0.5 py-2 text-[11px] ${page === p.id ? 'text-accent' : 'text-muted'}`}>
            <p.icon size={21} />{p.label}
          </a>
        ))}
        <button onClick={() => setMore(true)} className={`flex flex-col items-center gap-0.5 py-2 text-[11px] ${!MOBILE_TABS.includes(page) ? 'text-accent' : 'text-muted'}`}>
          <span className="relative"><Menu size={21} />{unread > 0 && <span className="absolute -top-1 -right-1.5 size-2.5 rounded-full bg-accent" />}</span>{tr("Ещё")}
        </button>
      </nav>
      {phone && <Suspense fallback={null}><MobileAppModal onClose={() => setPhone(false)} install={install ? () => { installApp(); setPhone(false) } : undefined} /></Suspense>}
      {more && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm md:hidden" onClick={() => setMore(false)}>
          <div className="absolute inset-x-0 bottom-0 space-y-1 rounded-t-3xl border-t border-line bg-panel p-4" onClick={(e) => e.stopPropagation()}
               style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}>
            <div className="mb-2 flex items-center justify-between px-2">
              <span className="text-sm text-muted">{me?.username} · {me ? ROLE_NAMES[me.role] : ''}</span>
              <button onClick={() => setMore(false)} className="p-1 text-muted"><X size={18} /></button>
            </div>
            {visible.filter((p) => !MOBILE_TABS.includes(p.id)).map(navLink)}
            {install && <button className="btn btn-ghost mt-2 w-full" onClick={installApp}><Download size={16} />{tr("Установить приложение")}</button>}
            <button className="btn btn-primary mt-2 w-full" onClick={() => { setMore(false); setPhone(true) }}><Smartphone size={16} />{tr("Установить как приложение")}</button>
            <LangSwitch className="mt-2" />
            <button className="btn btn-ghost mt-2 w-full" onClick={logout}><LogOut size={16} />{tr("Выйти")}</button>
          </div>
        </div>
      )}
    </div>
  )
}
