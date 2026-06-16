import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi, type UserInfo } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserInfo | null>(null)
  const isAuthenticated = ref(false)

  async function login(username: string, password: string) {
    const res = await authApi.login({ username, password })
    localStorage.setItem('access_token', res.access_token)
    localStorage.setItem('refresh_token', res.refresh_token)
    isAuthenticated.value = true
    await fetchCurrentUser()
  }

  async function register(username: string, email: string, password: string) {
    await authApi.register({ username, email, password })
  }

  async function fetchCurrentUser() {
    try {
      user.value = await authApi.getCurrentUser()
      isAuthenticated.value = true
    } catch {
      isAuthenticated.value = false
      user.value = null
    }
  }

  async function logout() {
    try {
      await authApi.logout()
    } finally {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      isAuthenticated.value = false
      user.value = null
    }
  }

  // 初始化时检查token
  function init() {
    const token = localStorage.getItem('access_token')
    if (token) {
      fetchCurrentUser()
    }
  }

  return { user, isAuthenticated, login, register, fetchCurrentUser, logout, init }
})
