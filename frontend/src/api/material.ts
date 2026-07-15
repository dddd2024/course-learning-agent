import request from './index'
import type { AxiosPromise, AxiosProgressEvent } from 'axios'

export type MaterialStatus = 'uploaded' | 'processing' | 'ready' | 'failed'
export type MaterialIdentifier = number | string
export type ReaderMode = 'page' | 'structured_text' | 'raw'

export interface ReaderCapability {
  usable: boolean
  preferred_mode: ReaderMode | null
  available_modes: ReaderMode[]
  blocking_reasons: string[]
}

export interface AssistantCapability {
  usable: boolean
  degraded: boolean
  retrieval_mode: 'fts_bm25' | 'keyword_fallback'
  reasons: string[]
}

export interface Material {
  id: number
  public_id: string
  filename: string
  file_url?: string | null
  file_type: string
  status: MaterialStatus
  version: number
  active_version_id?: number | null
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

export interface MaterialReadiness {
  material_id: number
  status: MaterialStatus
  active_version_id: number | null
  version_status: string | null
  file_type: string
  parse_job_status: ParseJobStatus | null
  parse_error: string | null
  active_chunk_count: number
  indexable_chunk_count: number
  material_page_count: number
  expected_page_numbers: number[]
  ready_page_numbers: number[]
  missing_page_numbers: number[]
  fts_indexed_chunk_count: number
  reader_mode: 'page' | 'structured_text'
  document_mode: 'text_pdf' | 'scanned_pdf' | 'non_pdf_text' | 'unexpected_empty_text_pdf' | 'unknown_pdf'
  expected_page_count: number
  persisted_page_count: number
  asset_page_count: number
  effective_page_count: number
  page_catalog_missing_numbers: number[]
  page_catalog_synthetic_numbers: number[]
  page_asset_missing_numbers: number[]
  page_asset_invalid_numbers: number[]
  page_catalog_consistent: boolean
  page_assets_complete: boolean
  warnings: string[]
  usable: boolean
  blocking_reasons: string[]
  reader: ReaderCapability
  assistant: AssistantCapability
  assets: {
    page_status: 'ready' | 'partial' | 'missing' | 'not_applicable'
    expected_pages: number
    ready_pages: number
    standalone_image_status: string
    document_readable: boolean
  }
  telemetry_warnings: string[]
  repair: { needed: boolean; actions: string[] }
}

export function getMaterialReadiness(materialId: MaterialIdentifier): AxiosPromise<MaterialReadiness> {
  return request.get(`/materials/${materialId}/readiness`)
}

export function rebuildMaterialFts(materialId: MaterialIdentifier): AxiosPromise<{
  material_id: number
  before_count: number
  indexed_count: number
  indexable_chunk_count: number
  changed: boolean
}> {
  return request.post(`/materials/${materialId}/fts/rebuild`)
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
  catalog_key: string
  id: number | null
  page_no: number
  page_type: string
  parser_version: string | null
  raw_text: string
  clean_text: string
  removed_lines: string
  blocks: string
  source_width?: number | null
  source_height?: number | null
  text_layer: Array<{
    block_id: string
    text: string
    bbox: [number, number, number, number]
    reading_order: number
    font_size?: number | null
  }>
  is_synthetic: boolean
  page_asset?: {
    id: number
    file_url: string
    width?: number | null
    height?: number | null
    dpi?: number | null
    sha256?: string | null
    status: 'ready' | 'failed' | 'pending'
    error_code?: string | null
  } | null
}

export interface MaterialPageCatalog {
  material_id: number
  material_version_id: number | null
  expected_pages: number
  persisted_pages: number
  asset_pages: number
  effective_pages: number
  missing_catalog_page_numbers: number[]
  synthetic_page_numbers: number[]
  items: MaterialPage[]
}

export function getMaterialPages(materialId: MaterialIdentifier): AxiosPromise<MaterialPageCatalog> {
  return request.get(`/materials/${materialId}/pages`)
}

export type ImageIntegrityStatus = 'ready' | 'partial' | 'missing' | 'unsupported' | 'page_fallback_ready'

export interface ImageIntegrityResult {
  material_id: number
  total: number
  ready: number
  missing: number
  page_assets: number
  page_assets_ready: number
  expected_pages: number
  ready_pages: number
  missing_pages: number
  status: string
}

export function getImageIntegrity(materialId: MaterialIdentifier): AxiosPromise<ImageIntegrityResult> {
  return request.get(`/materials/${materialId}/image-integrity`)
}

export interface ReextractResult {
  material_id: number
  status: string
  code?: string | null
  found?: number
  extracted: number
}

export function reextractImages(materialId: MaterialIdentifier): AxiosPromise<ReextractResult> {
  return request.post(`/materials/${materialId}/images/reextract`)
}

export type RepairStepStatus = 'success' | 'failed' | 'skipped' | 'restored_previous_assets'

export interface PageAssetRebuildResult {
  expected_pages: number
  ready_pages: number
  missing_pages: number
  status: 'ready' | 'readable_but_not_repaired' | 'failed'
  reader_state: 'fully_repaired' | 'synthetic_fallback' | 'unavailable'
  page_asset_rebuild: { status: RepairStepStatus; replaced?: number }
  page_catalog_backfill: { status: RepairStepStatus; created: number; remaining_synthetic_page_numbers: number[] }
  error_code?: string | null
}

export function rebuildPageAssets(materialId: MaterialIdentifier): AxiosPromise<PageAssetRebuildResult> {
  return request.post(`/materials/${materialId}/page-assets/rebuild`)
}

export type ParseJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface ParseJob {
  id: number
  status: ParseJobStatus
  attempt: number
  started_at?: string | null
  heartbeat_at?: string | null
  error?: string | null
}

export interface ParseJobListResult {
  items: ParseJob[]
}

export function getParseJobs(materialId: number): AxiosPromise<ParseJobListResult> {
  return request.get(`/materials/${materialId}/parse-jobs`)
}

export function retryParseJob(materialId: number, jobId: number): AxiosPromise<{ job_id: number; status: ParseJobStatus }> {
  return request.post(`/materials/${materialId}/parse-jobs/${jobId}/retry`)
}

export function cancelParseJob(materialId: number, jobId: number): AxiosPromise<{ job_id: number; status: ParseJobStatus }> {
  return request.post(`/materials/${materialId}/parse-jobs/${jobId}/cancel`)
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

export function parseMaterial(materialId: MaterialIdentifier): AxiosPromise<ParseResult> {
  return request.post(`/materials/${materialId}/parse`)
}

export function deleteMaterial(
  materialId: MaterialIdentifier,
): AxiosPromise<void> {
  return request.delete(`/materials/${materialId}`)
}

export function getChunks(
  materialId: MaterialIdentifier,
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
  materialId: MaterialIdentifier,
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
  materialId: MaterialIdentifier,
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
