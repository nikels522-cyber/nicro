import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { tr } from '../i18n'
import { installHint, isIOS, panelUrl, standalone } from './install'

const ua = () => navigator.userAgent
const isAndroid = () => /Android/i.test(ua())
const isIOSSafari = () => /Safari\//.test(ua()) && !/CriOS|FxiOS|EdgiOS|YaBrowser|OPiOS|GSA|Telegram|Instagram|FBAN/.test(ua())
const inApp = () => / nicroApp\//.test(ua())  // already inside the Android app

async function copyPanelUrl() {
  try { await navigator.clipboard.writeText(panelUrl()) } catch { /* the app also accepts a typed address */ }
}

/** Installing nicro on this device in any browser:
 *  Android — the nicro app (APK, opens the panel by itself: the address is copied to the clipboard first);
 *  iPhone — a configuration profile with a full-screen Home Screen icon;
 *  plus the browser's own install button when it offers one. */
export function InstallAction({ install, auto = false }: { install?: () => void; auto?: boolean }) {
  const [apkStarted, setApkStarted] = useState(false)
  const [profileStarted, setProfileStarted] = useState(false)
  // iPhone opened the install link: start the Home Screen profile right away (once per visit). Safari asks
  // "Allow", then Settings → Install — iOS lets no website add an icon without that confirmation.
  useEffect(() => {
    if (!auto || !isIOS() || !isIOSSafari() || standalone()) return
    try { if (sessionStorage.getItem('nicro-profile')) return; sessionStorage.setItem('nicro-profile', '1') } catch { /* private mode */ }
    setProfileStarted(true)
    const t = setTimeout(() => { location.href = './nicro.mobileconfig' }, 600)
    return () => clearTimeout(t)
  }, [auto])

  if (standalone() || inApp()) return <div className="text-sm text-emerald-300">{tr("Панель уже открыта как приложение.")}</div>

  if (isAndroid()) {
    return (
      <div className="space-y-2">
        <a className="btn btn-primary w-full py-3 text-base" href="./nicro.apk" onClick={() => { copyPanelUrl(); setApkStarted(true) }}>
          <Download size={18} />{tr("Скачать приложение nicro")}
        </a>
        {apkStarted
          ? <ol className="list-decimal space-y-0.5 pl-5 text-xs text-muted">
              <li>{tr("Откройте скачанный файл nicro.apk (шторка уведомлений или «Загрузки»).")}</li>
              <li>{tr("Если телефон спросит — разрешите установку из этого браузера и нажмите «Установить».")}</li>
              <li>{tr("Откройте nicro: адрес панели уже скопирован, приложение подставит его само.")}</li>
            </ol>
          : <div className="text-xs text-muted">{tr("Работает в любом браузере: скачается маленькое приложение nicro (30 КБ), которое откроет вашу панель.")}</div>}
        {install && <button type="button" className="btn btn-ghost w-full" onClick={install}>{tr("Или установить через браузер")}</button>}
      </div>
    )
  }

  if (isIOS()) {
    if (!isIOSSafari()) {
      return <div className="text-sm text-muted">{tr("Откройте эту страницу в Safari (меню браузера → «Открыть в Safari») — установка на iPhone работает только оттуда.")}</div>
    }
    return (
      <div className="space-y-2">
        {profileStarted && <div className="rounded-xl bg-accent/10 px-3 py-2 text-sm">{tr("Загружаю иконку nicro… Нажмите «Разрешить» в окне Safari.")}</div>}
        <a className="btn btn-primary w-full py-3 text-base" href="./nicro.mobileconfig" onClick={() => setProfileStarted(true)}><Download size={18} />{profileStarted ? tr("Загрузить ещё раз") : tr("Установить иконку nicro")}</a>
        <ol className="list-decimal space-y-0.5 pl-5 text-xs text-muted">
          <li>{tr("Нажмите «Разрешить» — профиль загрузится.")}</li>
          <li>{tr("Откройте «Настройки» → вверху «Профиль загружен» → «Установить».")}</li>
          <li>{tr("Иконка nicro появится на экране «Домой» и откроет панель на весь экран.")}</li>
        </ol>
        <div className="text-xs text-muted">{tr("Или без профиля: «Поделиться» → «На экран „Домой“».")}</div>
      </div>
    )
  }

  // computers: the browser's own install, or what to do in this browser
  if (install) return <button type="button" className="btn btn-primary w-full py-3 text-base" onClick={install}>{tr("Установить nicro")}</button>
  return <div className="text-sm text-muted">{installHint()}</div>
}
