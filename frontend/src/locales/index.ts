import { createI18n } from 'vue-i18n'
import zh from './zh'
import en from './en'

const savedLang = localStorage.getItem('dc_language') || 'zh'

const i18n = createI18n({
  legacy: false,
  locale: savedLang,
  fallbackLocale: 'zh',
  messages: {
    zh,
    en,
  },
})

export default i18n
