import client from './client'

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface UserResponse {
  id: string
  username: string
  has_cv: boolean
}

export const login = (username: string, password: string) =>
  client.post<TokenResponse>('/auth/login', { username, password }).then(r => r.data)

export const register = (username: string, password: string) =>
  client.post<TokenResponse>('/auth/register', { username, password }).then(r => r.data)

export const me = () =>
  client.get<UserResponse>('/auth/me').then(r => r.data)
