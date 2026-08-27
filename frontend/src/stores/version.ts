import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/api/index'

export const useVersionStore = defineStore('version', () => {
  const version = ref('')

  async function loadVersion() {
    try {
      const res: any = await api.get('/config/version')
      version.value = res.version || ''
    } catch {
      version.value = ''
    }
    return version.value
  }

  return { version, loadVersion }
})
