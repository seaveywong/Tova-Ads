import { createI18n } from 'vue-i18n'
import zh from './locales/zh'
import en from './locales/en'

const STORAGE_KEY = 'tova_locale'

// 语言检测：用户手动选过 > 浏览器语言 > 默认中文
function detectLocale() {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'zh' || saved === 'en') return saved
  const nav = (navigator.language || 'zh').toLowerCase()
  return nav.startsWith('en') ? 'en' : 'zh'
}

const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: 'en',
  messages: { zh, en },
})

export default i18n
