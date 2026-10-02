// Panel localization. Every UI string is written in Russian and wrapped in tr(); other languages map
// the Russian text to a translation (locales/<lang>.json). Placeholders: tr("Осталось {0} дн.", n).
// New strings: write them in Russian inside tr(...), run `node scripts/i18n-wrap.mjs --keys` and add
// the translations of the new keys to locales/en.json.
import en from './locales/en.json'

export const LANGS = { ru: 'Русский', en: 'English' } as const
export type Lang = keyof typeof LANGS

const dicts: Partial<Record<Lang, Record<string, string>>> = { en }

function detect(): Lang {
  try {
    const saved = localStorage.getItem('lang') as Lang | null
    if (saved && saved in LANGS) return saved
  } catch { /* storage unavailable */ }
  return navigator.language?.toLowerCase().startsWith('ru') ? 'ru' : 'en'
}

export const LANG: Lang = detect()
export const LOCALE = LANG === 'ru' ? 'ru-RU' : 'en-GB'
document.documentElement.lang = LANG

export function tr(s: string, ...args: unknown[]): string {
  const out = dicts[LANG]?.[s] || s
  return args.length ? out.replace(/\{(\d+)\}/g, (_, i) => String(args[+i] ?? '')) : out
}

export function setLang(l: Lang) {
  try { localStorage.setItem('lang', l) } catch { /* ignore */ }
  location.reload()  // module-level labels are evaluated once: a reload applies the language everywhere
}
