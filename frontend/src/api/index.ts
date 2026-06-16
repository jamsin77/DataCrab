import axios from 'axios'
import type { AxiosInstance, AxiosResponse } from 'axios'

const api: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器
api.interceptors.response.use(
  (response: AxiosResponse) => response.data,
  async (error) => {
    if (error.response) {
      const { status, data } = error.response
      if (status === 401) {
        // 登录接口的401直接返回错误，不尝试刷新token
        const isLoginRequest = error.config.url?.includes('/auth/login') || error.config.url?.includes('/auth/register')
        if (isLoginRequest) {
          return Promise.reject(error)
        }
        // Token过期，尝试刷新
        const refreshToken = localStorage.getItem('refresh_token')
        if (refreshToken) {
          try {
            const res = await axios.post('/api/v1/auth/refresh', {
              refresh_token: refreshToken,
            })
            localStorage.setItem('access_token', res.data.access_token)
            localStorage.setItem('refresh_token', res.data.refresh_token)
            // 重试原请求
            error.config.headers.Authorization = `Bearer ${res.data.access_token}`
            return api(error.config)
          } catch {
            localStorage.removeItem('access_token')
            localStorage.removeItem('refresh_token')
            window.location.href = '/login'
          }
        } else {
          window.location.href = '/login'
        }
      }
      // 其他错误不在这里显示ElMessage，由调用方处理
    }
    return Promise.reject(error)
  }
)

export default api
