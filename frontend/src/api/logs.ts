import request from './index'
import type { AxiosPromise } from 'axios'

// Task A: frontend-originated categories are included so the log center
// can classify browser-side failures alongside server-side ones.
export type ErrorLogCategory =
  | 'upload'
  | 'parse'
  | 'agent'
  | 'search'
  | 'system'
  | 'frontend'
  | 'network'
  | 'api'
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

// Task A: frontend error reporting. Posts a failed API/network request
// to the log center. The backend redacts sensitive substrings before
// persistence. This call is marked `skipReport` so a failure here does
// not recurse into another report (infinite loop protection is also in
// the axios interceptor).
export interface FrontendErrorReportPayload {
  category: ErrorLogCategory
  level?: ErrorLogLevel
  title: string
  message: string
  technical_detail?: string | null
  request_path?: string | null
  frontend_route?: string | null
  status_code?: number | null
}

export function reportErrorLog(
  payload: FrontendErrorReportPayload,
): AxiosPromise<ErrorLog> {
  return request.post('/logs', payload, {
    // Custom flag read by the axios error interceptor to avoid recursion.
    headers: { 'X-Skip-Error-Report': '1' },
  } as Record<string, unknown>)
}
