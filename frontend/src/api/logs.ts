import request from './index'
import type { AxiosPromise } from 'axios'

export type ErrorLogCategory = 'upload' | 'parse' | 'agent' | 'search' | 'system'
export type ErrorLogLevel = 'warning' | 'error'
export type ErrorLogStatus = 'open' | 'resolved' | 'ignored'

export interface ErrorLog {
  id: number
  category: ErrorLogCategory
  level: ErrorLogLevel
  status: ErrorLogStatus
  title: string
  message: string
  technical_detail?: string | null
  course_id?: number | null
  material_id?: number | null
  agent_run_id?: number | null
  request_path?: string | null
  retry_count: number
  max_retries?: number | null
  created_at: string
  updated_at: string
}

export interface ErrorLogListResult {
  items: ErrorLog[]
  total: number
  page: number
  page_size: number
}

export interface ErrorLogListParams {
  category?: ErrorLogCategory
  level?: ErrorLogLevel
  status?: ErrorLogStatus
  material_id?: number
  agent_run_id?: number
  keyword?: string
  page?: number
  page_size?: number
}

export function listErrorLogs(
  params?: ErrorLogListParams,
): AxiosPromise<ErrorLogListResult> {
  return request.get('/logs', { params })
}

export function getErrorLog(id: number): AxiosPromise<ErrorLog> {
  return request.get(`/logs/${id}`)
}

export function resolveErrorLog(
  id: number,
  status: ErrorLogStatus = 'resolved',
): AxiosPromise<ErrorLog> {
  return request.post(`/logs/${id}/resolve`, { status })
}
