import request from './index'
import type { AxiosPromise, AxiosProgressEvent } from 'axios'

export type MaterialStatus = 'uploaded' | 'processing' | 'ready' | 'failed'

export interface Material {
  id: number
  filename: string
  file_type: string
  status: MaterialStatus
  version: number
  error_message?: string | null
  uploaded_at: string
}

export interface MaterialListResult {
  items: Material[]
  total: number
}

export interface MaterialListParams {
  type?: string
  status?: MaterialStatus
}

export interface ParseResult {
  material_id: number
  status: MaterialStatus
  chunk_count: number
}

export interface Chunk {
  id: number
  chunk_index: number
  title: string
  page_no: number
  text: string
  keyword_text?: string
}

export interface ChunkListResult {
  items: Chunk[]
  total: number
  page: number
  page_size: number
}

export interface ChunkListParams {
  page?: number
  page_size?: number
}

export interface SearchItem {
  chunk_id: number
  material_id: number
  filename: string
  page_no: number
  title: string
  text: string
  score: number
}

export interface SearchResult {
  items: SearchItem[]
  total: number
}

export interface SearchParams {
  course_id: number
  keyword: string
  top_k?: number
}

export interface UploadOptions {
  onUploadProgress?: (event: AxiosProgressEvent) => void
}

export function listMaterials(
  courseId: number,
  params?: MaterialListParams,
): AxiosPromise<MaterialListResult> {
  return request.get(`/courses/${courseId}/materials`, { params })
}

export function uploadMaterial(
  courseId: number,
  file: File,
  options?: UploadOptions,
): AxiosPromise<Material> {
  const formData = new FormData()
  formData.append('file', file)
  return request.post(`/courses/${courseId}/materials`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: options?.onUploadProgress,
    timeout: 0,
  })
}

export function parseMaterial(materialId: number): AxiosPromise<ParseResult> {
  return request.post(`/materials/${materialId}/parse`)
}

export function deleteMaterial(
  materialId: number,
): AxiosPromise<void> {
  return request.delete(`/materials/${materialId}`)
}

export function getChunks(
  materialId: number,
  params?: ChunkListParams,
): AxiosPromise<ChunkListResult> {
  return request.get(`/materials/${materialId}/chunks`, { params })
}

// Phase 2 Task C/D: material overview (chunk stats + security findings).
export interface MaterialOverview {
  material_id: number
  status: MaterialStatus
  chunk_count: number
  page_range: number[] | null
  section_count: number
  keywords: string[]
  warnings: string[]
  security_findings_count: number
}

export function getMaterialOverview(
  materialId: number,
): AxiosPromise<MaterialOverview> {
  return request.get(`/materials/${materialId}/overview`)
}

// Phase 2 bugfix P0-2: fetch a single chunk's full text for citation
// evidence display. The backend assembles display_label; the frontend
// just needs the raw text for highlighting.
export interface ChunkDetail {
  chunk_id: number
  material_id: number
  material_name: string
  title: string | null
  page_no: number | null
  text: string
}

export function getChunk(chunkId: number): AxiosPromise<ChunkDetail> {
  return request.get(`/chunks/${chunkId}`)
}

export function search(params: SearchParams): AxiosPromise<SearchResult> {
  return request.get('/search', { params })
}
