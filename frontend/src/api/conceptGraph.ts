import request from './index'
import type { AxiosPromise } from 'axios'

export interface GraphNode {
  id: number
  user_id: number
  course_id: number
  knowledge_point_id: number | null
  title: string
  normalized_title: string
  summary: string
  aliases: string[]
  importance: number
  source_chunk_ids: number[]
  weak_point_score: number
}

export interface GraphEdge {
  id: number
  user_id: number
  source_node_id: number
  target_node_id: number
  relation_type: string
  confidence: number
  reason: string
  evidence_chunk_ids: number[]
  status: string
  audit_run_id: number | null
}

export interface GraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface RebuildResponse {
  nodes_count: number
  edges_count: number
}

export interface NodeDetail extends GraphNode {
  related_edges: GraphEdge[]
}

export interface CompareReport {
  id: number
  source_node_id: number
  target_node_id: number
  edge_id: number | null
  report_json: Record<string, any>
  citation_chunk_ids: number[]
  prompt_version: string
  provider: string
  model_name: string
  fallback_used: boolean
  fallback_reason: string
  audit_run_id: number | null
}

export function rebuildGraph(): AxiosPromise<RebuildResponse> {
  return request.post('/concept-graph/rebuild')
}

export function getGraph(params?: {
  course_ids?: string
  relation_type?: string
  status?: string
}): AxiosPromise<GraphResponse> {
  return request.get('/concept-graph', { params })
}

export function getNodeDetail(nodeId: number): AxiosPromise<NodeDetail> {
  return request.get(`/concept-graph/nodes/${nodeId}`)
}

export function confirmEdge(edgeId: number): AxiosPromise<GraphEdge> {
  return request.post(`/concept-graph/edges/${edgeId}/confirm`)
}

export function rejectEdge(edgeId: number): AxiosPromise<GraphEdge> {
  return request.post(`/concept-graph/edges/${edgeId}/reject`)
}

export function compareNodes(
  sourceNodeId: number,
  targetNodeId: number,
  edgeId?: number,
  userFocus: string = 'concept',
  forceRefresh = false,
): AxiosPromise<CompareReport> {
  // The compare endpoint calls the user's LLM which can take 50-90s.
  // Override the default 30s axios timeout so the request isn't
  // aborted before the backend finishes generating and caching the
  // report (which would leave the UI showing "暂无对比报告").
  return request.post(
    '/concept-graph/compare',
    {
      source_node_id: sourceNodeId,
      target_node_id: targetNodeId,
      edge_id: edgeId ?? null,
      user_focus: userFocus,
      force_refresh: forceRefresh,
    },
    { timeout: 120000 },
  )
}
