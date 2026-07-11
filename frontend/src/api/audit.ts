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

export interface FallbackChainStep {
  provider?: string
  model?: string
  status?: string
  reason?: string | null
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
  // V3-02: provider / model traceability fields
  provider: string | null
  requested_provider: string | null
  requested_model: string | null
  actual_provider: string | null
  actual_model: string | null
  fallback_used: boolean
  fallback_reason: string | null
  fallback_chain: FallbackChainStep[] | null
  evidence_status: string | null
  final_status: string | null
  config_id: number | null
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
