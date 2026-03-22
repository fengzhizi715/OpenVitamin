import { createI18n } from 'vue-i18n'
import en from './i18n/locales/en.json'
import zh from './i18n/locales/zh.json'

const saved = typeof localStorage !== 'undefined' ? localStorage.getItem('platform-language') : null
const fallback = (saved === 'zh' || saved === 'en') ? saved : 'en'

export const i18n = createI18n({
  legacy: false,
  locale: fallback,
  fallbackLocale: 'en',
  messages: {
    en,
    zh
  }
})
