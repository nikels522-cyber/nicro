import { useState } from 'react'
import { api, setToken } from '../api'
import { tr } from '../i18n'
import { LangSwitch } from '../components/brand'
import { isIOS, standalone } from '../components/install'
import { InstallAction } from '../components/InstallAction'

const wantsInstall = new URLSearchParams(location.search).has('install')

export default function Login({ onDone, install }: { onDone: () => void; install?: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [code, setCode] = useState('')
  const [need2fa, setNeed2fa] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const r = await api<{ token: string }>('/auth/login', { body: { username, password, code } })
      setToken(r.token)
      onDone()
    } catch (err: any) {
      if (err.message === '2FA_REQUIRED') { setNeed2fa(true); setError(''); return }
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-full place-items-center p-4"
         style={{ background: 'radial-gradient(60rem 40rem at 50% -10%, rgba(124,108,255,.22), transparent)' }}>
      <div className="w-full max-w-sm space-y-4">
      {!standalone() && (install || wantsInstall || isIOS() || /Android/i.test(navigator.userAgent)) && (
        <div className="card space-y-3 border-accent/50 bg-gradient-to-br from-accent/15 to-accent-2/5 p-5">
          <div className="flex items-center gap-3">
            <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-accent to-accent-2 text-xl font-black text-white">n</div>
            <div><div className="font-semibold">{tr("Приложение nicro")}</div><div className="text-xs text-muted">{tr("Иконка на рабочем столе, весь экран, без адресной строки")}</div></div>
          </div>
          <InstallAction install={install} auto={wantsInstall} />
          <div className="text-xs text-muted">{tr("Войти можно сразу или уже в установленном приложении.")}</div>
        </div>
      )}
      <form onSubmit={submit} className="card w-full space-y-4 p-8">
        <div className="flex flex-col items-center gap-3 pb-2">
          <div className="grid size-16 place-items-center rounded-3xl bg-gradient-to-br from-accent to-accent-2 text-3xl font-black text-white shadow-xl shadow-accent/30">n</div>
          <h1 className="text-2xl font-semibold tracking-tight">nicro</h1>
          <p className="-mt-2 text-sm text-muted">{tr("Панель управления VPN")}</p>
        </div>
        <div>
          <label className="label">{tr("Логин")}</label>
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
        </div>
        <div>
          <label className="label">{tr("Пароль")}</label>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </div>
        {need2fa && (
          <div>
            <label className="label">{tr("Код из приложения-аутентификатора")}</label>
            <input className="input text-center font-mono text-lg tracking-[0.4em]" inputMode="numeric" maxLength={6}
                   value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} autoFocus autoComplete="one-time-code" />
          </div>
        )}
        {error && <div className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>}
        <button className="btn btn-primary w-full" disabled={busy}>{busy ? tr("Вход…") : tr("Войти")}</button>
        <LangSwitch />
      </form>
      </div>
    </div>
  )
}
