import axios from 'axios'
import type { AxiosInstance, AxiosResponse } from 'axios'

const api: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
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
        // 登录/注册/重置密码接口的401直接返回错误，不尝试刷新token
        const isAuthRequest = error.config.url?.includes('/auth/login') 
          || error.config.url?.includes('/auth/register')
          || error.config.url?.includes('/auth/reset-password')
        if (isAuthRequest) {
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
    } else if (error.code === 'ERR_NETWORK' || error.message?.includes('Network')) {
      // 网络错误：后端可能正在 reload（开发模式改代码触发 uvicorn 重启）
      // 不跳转登录页，让调用方 catch 处理；给一个友好错误消息
      error.message = '后端服务暂时不可用，可能正在重启，请稍后重试'
    }
    return Promise.reject(error)
  }
)

export default api
