import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/api/index'

export const useVersionStore = defineStore('version', () => {
  const version = ref('')
  const loaded = ref(false)

  async function loadVersion() {
    if (loaded.value) return version.value
    try {
      const res: any = await api.get('/config/version')
      version.value = res.version || ''
      loaded.value = true
    } catch {
      version.value = ''
    }
    return version.value
  }

  return { version, loaded, loadVersion }
})
