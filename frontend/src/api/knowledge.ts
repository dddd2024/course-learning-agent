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
  status?: string
  stable_key?: string | null
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
  params?: { page?: number; page_size?: number; include_archived?: boolean },
): AxiosPromise<KnowledgeListResult> {
  return request.get(`/courses/${courseId}/knowledge-points`, { params })
}

export interface KPGeneration {
  generation: number
  status: string
  count: number
  created_at: string | null
}

export function getKPGenerations(
  courseId: number,
): AxiosPromise<KPGeneration[]> {
  return request.get(`/courses/${courseId}/knowledge-points/generations`)
}
