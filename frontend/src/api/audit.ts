import request from './index'
import type { AxiosPromise } from 'axios'

export interface AgentRunListParams {
  run_type?: string
  status?: string
  limit?: number
  offset?: number
}

export interface AgentStep {
  id: number
  run_id: number
  step_name: string
  step_index: number
  input_data: unknown
  output_data: unknown
  duration_ms: number | null
  status: string
  error_message: string | null
  created_at: string | null
}

export interface AgentRun {
  id: number
  user_id: number
  run_type: string
  status: string
  input_summary: unknown
  output_summary: unknown
  prompt_version: string | null
  model_name: string | null
  duration_ms: number | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string | null
}

export interface AgentRunDetail extends AgentRun {
  steps: AgentStep[]
}

export interface AgentRunListResult {
  items: AgentRun[]
  total: number
}

export function getAgentRuns(params?: AgentRunListParams): AxiosPromise<AgentRunListResult> {
  return request.get('/agent-runs', { params })
}

export function getAgentRun(id: number): AxiosPromise<AgentRunDetail> {
  return request.get(`/agent-runs/${id}`)
}
