import request from './index'
import type { AxiosPromise } from 'axios'

export interface LoginPayload {
  username: string
  password: string
}

export interface LoginResult {
  access_token: string
  token_type: string
}

export interface RegisterPayload {
  username: string
  password: string
  email?: string
}

export interface RegisterResult {
  user_id: number
  username: string
}

export interface UserInfo {
  id: number
  username: string
  email_masked: string | null
}

export interface ApiError {
  code: number | string
  message: string
}

export function login(payload: LoginPayload): AxiosPromise<LoginResult> {
  return request.post('/auth/login', payload)
}

export function register(payload: RegisterPayload): AxiosPromise<RegisterResult> {
  return request.post('/auth/register', payload)
}

export function getMe(): AxiosPromise<UserInfo> {
  return request.get('/auth/me')
}

export interface SecurityStatus {
  password_storage: string
  api_key_storage: string
  token_expiry_minutes: number
  environment: string
  using_default_secret: boolean
}

export function getSecurityStatus(): AxiosPromise<SecurityStatus> {
  return request.get('/auth/security-status')
}
