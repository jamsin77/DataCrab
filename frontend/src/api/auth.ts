import api from './index'

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
  display_name?: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface UserInfo {
  id: string
  username: string
  email: string
  display_name: string | null
  avatar: string | null
  is_active: boolean
  is_superuser: boolean
}

export const authApi = {
  login(data: LoginRequest): Promise<TokenResponse> {
    return api.post('/auth/login', data)
  },

  register(data: RegisterRequest): Promise<UserInfo> {
    return api.post('/auth/register', data)
  },

  refreshToken(refresh_token: string): Promise<TokenResponse> {
    return api.post('/auth/refresh', { refresh_token })
  },

  getCurrentUser(): Promise<UserInfo> {
    return api.get('/auth/me')
  },

  logout(): Promise<void> {
    return api.post('/auth/logout')
  },

  resetPassword(username: string, old_password: string, new_password: string): Promise<{ message: string }> {
    return api.post('/auth/reset-password', { username, old_password, new_password })
  },
}
