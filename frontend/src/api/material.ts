import request from './index'
import type { AxiosPromise, AxiosProgressEvent } from 'axios'

export type MaterialStatus = 'uploaded' | 'processing' | 'ready' | 'failed'

export interface Material {
  id: number
  filename: string
  file_url?: string | null
  file_type: string
  status: MaterialStatus
  version: number
  error_message?: string | null
  uploaded_at: string
  parse_started_at?: string | null
  parse_finished_at?: string | null
  parse_attempts?: number
  last_parse_error?: string | null
}

export interface MaterialListResult {
  items: Material[]
  total: number
}

export interface MaterialListParams {
  type?: string
  status?: MaterialStatus
  page?: number
  page_size?: number
}

export interface ParseResult {
  material_id: number
  status: MaterialStatus
  chunk_count: number
}

export interface ChunkImage {
  id: number
  page_no: number
  status?: 'loading' | 'ready' | 'missing' | 'forbidden' | 'error'
  missing_reason?: string | null
  file_url?: string | null
  width?: number
  height?: number
  format: string
  is_decorative?: boolean
  decorative_reason?: string | null
  color_variance?: number | null
  coverage_ratio?: number | null
}

export interface MaterialPage {
  id: number
  page_no: number
  page_type: string
  parser_version: string
  raw_text: string
  clean_text: string
  removed_lines: string
  blocks: string
}

export function getMaterialPages(materialId: number): AxiosPromise<{ items: MaterialPage[] }> {
  return request.get(`/materials/${materialId}/pages`)
}

export function getImageIntegrity(materialId: number): AxiosPromise<{ total: number; ready: number; missing: number; status: string }> {
  return request.get(`/materials/${materialId}/image-integrity`)
}

export function reextractImages(materialId: number): AxiosPromise<{ status: string; code?: string; extracted: number }> {
  return request.post(`/materials/${materialId}/images/reextract`)
}

export interface Chunk {
  id: number
  chunk_index: number
  title: string
  page_no: number
  text: string
  keyword_text?: string
  images?: ChunkImage[]
  quality_score?: number | null
  quality_reason?: string | null
  // LEARN-V3-01: JSON string of noise type flags, or null when clean
  noise_flags?: string | null
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
  include_decorative?: boolean
}

export interface SearchItem {
  chunk_id: number
  material_id: number
  filename: string
  page_no: number
  title: string
  text: string
  snippet: string
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

export interface MaterialStudyGuide {
  material_id: number
  answer: string
  evidence_ids: number[]
  sampled_pages: number[]
  coverage_note: string
  provider: string
  fallback_used: boolean
  fallback_reason?: string | null
  agent_run_id?: number | null
}

export function generateMaterialStudyGuide(
  materialId: number,
): AxiosPromise<MaterialStudyGuide> {
  return request.post(`/materials/${materialId}/study-guide`)
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
