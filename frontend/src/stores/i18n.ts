import { defineStore } from 'pinia'
import { ref } from 'vue'
import i18n from '@/locales'

export const useI18nStore = defineStore('i18n', () => {
  const locale = ref(localStorage.getItem('dc_language') || 'zh')

  function setLocale(lang: 'zh' | 'en') {
    locale.value = lang
    i18n.global.locale.value = lang
    localStorage.setItem('dc_language', lang)
  }

  function toggle() {
    setLocale(locale.value === 'zh' ? 'en' : 'zh')
  }

  return { locale, setLocale, toggle }
})
