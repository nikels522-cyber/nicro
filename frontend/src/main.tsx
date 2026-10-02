import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'

// The browser tells once that the app can be installed — possibly before React is mounted: keep it.
addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault()
  ;(window as any).__nicroInstall = e
  dispatchEvent(new Event('nicro-install'))
})
addEventListener('appinstalled', () => { (window as any).__nicroInstall = null; dispatchEvent(new Event('nicro-install')) })

// installable app (PWA): the service worker lives under the panel's secret path
if ('serviceWorker' in navigator) {
  addEventListener('load', () => navigator.serviceWorker.register('./sw.js').catch(() => {}))
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
