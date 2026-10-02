import { useState } from 'react'
import { Check, Copy, Monitor, Smartphone } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { Modal } from './ui'
import { tr } from '../i18n'

import { isIOS, isMobile, openedForInstall, panelUrl } from './install'
import { InstallAction } from './InstallAction'

/** "The panel as a phone app": QR to open it on the phone + how to install (PWA) on Android / iPhone. */
export function MobileAppModal({ onClose, install }: { onClose: () => void; install?: () => void }) {
  const [copied, setCopied] = useState(false)
  const url = panelUrl() + '?install=1'  // opened from the QR: install is offered first
  return (
    <Modal title={tr("📱 Приложение nicro")} onClose={onClose}>
      <div className="space-y-4 text-sm">
        <div className="rounded-2xl border border-accent/40 bg-accent/5 p-3">
          <div className="mb-2 flex items-center gap-2 font-medium">{isMobile() ? <Smartphone size={16} /> : <Monitor size={16} />}{tr("На этом устройстве")}</div>
          <InstallAction install={install} auto={openedForInstall} />
        </div>
        <div className="font-medium">{tr("На телефоне")}</div>
        <div className="flex flex-col items-center gap-3 sm:flex-row sm:items-start">
          <div className="shrink-0 rounded-2xl bg-white p-3"><QRCodeSVG value={url} size={150} /></div>
          <div className="min-w-0 space-y-2">
            <div className="text-muted">{tr("Отсканируйте камерой телефона — панель откроется в браузере. Ссылку не публикуйте: в ней секретный путь панели.")}</div>
            <div className="flex gap-2">
              <input className="input font-mono text-xs" readOnly value={url} onFocus={(e) => e.target.select()} />
              <button className="btn btn-ghost px-2.5" onClick={() => navigator.clipboard.writeText(url).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })}>
                {copied ? <Check size={15} /> : <Copy size={15} />}
              </button>
            </div>
          </div>
        </div>
        <div className={`rounded-2xl border p-3 ${isIOS() ? 'border-line' : 'border-accent/40 bg-accent/5'}`}>
          <div className="mb-1 font-medium">{tr("Android (Chrome, Яндекс Браузер, Samsung)")}</div>
          <ol className="list-decimal space-y-0.5 pl-5 text-muted">
            <li>{tr("Откройте ссылку и войдите.")}</li>
            <li>{tr("Нажмите кнопку «Установить приложение» внизу меню «Ещё» — или меню браузера ⋮ → «Установить приложение» / «Добавить на главный экран».")}</li>
            <li>{tr("Иконка nicro появится на рабочем столе; панель откроется на весь экран, без адресной строки.")}</li>
          </ol>
        </div>
        <div className={`rounded-2xl border p-3 ${isIOS() ? 'border-accent/40 bg-accent/5' : 'border-line'}`}>
          <div className="mb-1 font-medium">{tr("iPhone и iPad (только Safari)")}</div>
          <ol className="list-decimal space-y-0.5 pl-5 text-muted">
            <li>{tr("Откройте ссылку в Safari и войдите.")}</li>
            <li>{tr("Нажмите «Поделиться» (квадрат со стрелкой) → «На экран „Домой“» → «Добавить».")}</li>
            <li>{tr("Запускайте nicro с рабочего стола как обычное приложение.")}</li>
          </ol>
        </div>
      </div>
    </Modal>
  )
}
