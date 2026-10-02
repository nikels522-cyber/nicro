// Installing the panel as an app (PWA): platform checks and what to tell users of each browser.
import { tr } from '../i18n'

export const panelUrl = () => location.origin + location.pathname.replace(/index\.html$/, '')
export const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent)
export const standalone = () => matchMedia('(display-mode: standalone)').matches || (navigator as any).standalone === true
export const isMobile = () => /android|iphone|ipad|ipod/i.test(navigator.userAgent)

/** Why there is no install button in this browser, and what to do instead. */
export function installHint(): string {
  const ua = navigator.userAgent
  if (/Android/.test(ua)) return tr("Меню браузера ⋮ (или ≡) → «Установить приложение» / «Добавить на главный экран». Если кнопки «Установить nicro» нет, подождите пару секунд или обновите страницу.")
  if (/OPR\/|Opera/.test(ua)) return tr("Opera не умеет устанавливать сайты как приложения. Откройте эту ссылку в Chrome, Edge или Яндекс Браузере — там появится кнопка «Установить».")
  if (/Firefox\//.test(ua)) return tr("Firefox не устанавливает сайты как приложения. Откройте ссылку в Chrome, Edge или Яндекс Браузере.")
  if (/YaBrowser/.test(ua)) return tr("Яндекс Браузер: меню ≡ → «Дополнительно» → «Установить приложение nicro» (или значок в адресной строке).")
  if (/Edg\//.test(ua)) return tr("Edge: значок «Приложение доступно» справа в адресной строке или меню … → «Приложения» → «Установить nicro».")
  if (/Chrome\//.test(ua)) return tr("Chrome: значок установки справа в адресной строке или меню ⋮ → «Сохранить и поделиться» → «Установить nicro». Если пункта нет — приложение уже установлено.")
  if (/Safari\//.test(ua) && !isIOS()) return tr("Safari на Mac: меню «Файл» → «Добавить в Dock».")
  return tr("Ваш браузер не предлагает установку. Откройте ссылку в Chrome, Edge или Яндекс Браузере.")
}

/** The browser's install prompt, caught as early as possible (main.tsx) so it is never missed. */
export const getInstallPrompt = (): any => (window as any).__nicroInstall ?? null

/** The page was opened from the install QR / link (captured at load: the address is cleaned up later). */
export const openedForInstall = new URLSearchParams(location.search).has('install')
