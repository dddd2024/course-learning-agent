import request from './index'
import type { AxiosPromise } from 'axios'

export interface KnowledgePoint {
  id: number | string
  title: string
  summary: string
  importance: number
  source_chunk_ids: number[]
  exam_style: string
  review_action: string
}

export interface GenerateKnowledgeResult {
  knowledge_points: KnowledgePoint[]
  count: number
}

export interface KnowledgeListResult {
  items: KnowledgePoint[]
  total: number
}

export function generateKnowledgePoints(
  courseId: number,
): AxiosPromise<GenerateKnowledgeResult> {
  return request.post(`/courses/${courseId}/knowledge-points/generate`)
}

export function listKnowledgePoints(
  courseId: number,
): AxiosPromise<KnowledgeListResult> {
  return request.get(`/courses/${courseId}/knowledge-points`)
}
