import request from './index'
import type { AxiosPromise } from 'axios'

export interface LLMConfig {
  id: number
  user_id: number
  provider: string
  name: string
  base_url: string
  model: string
  api_key_masked: string
  enabled: boolean
  is_default: boolean
  temperature: number
  max_tokens: number
  timeout_seconds: number
  last_test_status: string
  last_test_error: string | null
  last_test_at: string | null
  created_at: string | null
}

export interface LLMConfigCreate {
  provider: string
  name: string
  base_url: string
  model: string
  api_key: string
  temperature?: number
  max_tokens?: number
  timeout_seconds?: number
}

export interface LLMConfigUpdate {
  provider?: string
  name?: string
  base_url?: string
  model?: string
  api_key?: string
  temperature?: number
  max_tokens?: number
  timeout_seconds?: number
}

export interface LLMConfigTestResult {
  status: 'success' | 'failed'
  error: string | null
  provider: string
  model: string
}

export interface LLMConfigActiveResult {
  config: LLMConfig | null
}

export interface LLMConfigListResult {
  items: LLMConfig[]
}

export function listConfigs(): AxiosPromise<LLMConfigListResult> {
  return request.get('/llm-configs')
}

export function createConfig(data: LLMConfigCreate): AxiosPromise<LLMConfig> {
  return request.post('/llm-configs', data)
}

export function getActiveConfig(): AxiosPromise<LLMConfigActiveResult> {
  return request.get('/llm-configs/active')
}

export function updateConfig(
  id: number,
  data: LLMConfigUpdate,
): AxiosPromise<LLMConfig> {
  return request.put(`/llm-configs/${id}`, data)
}

export function deleteConfig(id: number): AxiosPromise<void> {
  return request.delete(`/llm-configs/${id}`)
}

export function enableConfig(id: number): AxiosPromise<LLMConfig> {
  return request.post(`/llm-configs/${id}/enable`)
}

export function testConfig(id: number): AxiosPromise<LLMConfigTestResult> {
  return request.post(`/llm-configs/${id}/test`)
}
