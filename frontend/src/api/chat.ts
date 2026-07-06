import request from './index'
import type { AxiosPromise } from 'axios'

export interface Conversation {
  id: number
  course_id: number
  title: string
  created_at: string
}

export interface ConversationListResult {
  items: Conversation[]
  total: number
}

export interface ConversationPayload {
  course_id: number
  title?: string
}

export interface Citation {
  chunk_id: number
  material_name: string
  page_no: number
  quote_text: string
  confidence: number
  material_id?: number
}

export interface RetrievedChunk {
  chunk_id: number
  score: number
  title: string | null
  page_no: number | null
  snippet: string
  is_cited: boolean
}

export type ReliabilityLevel = 'high' | 'medium' | 'low' | 'failed'

export interface CitationListResult {
  items: Citation[]
  total: number
}

export interface ChatPayload {
  course_id: number
  conversation_id: number
  question: string
}

export interface ChatResult {
  message_id: number
  answer: string
  citations: Citation[]
  not_found: boolean
  follow_up_questions: string[]
  reliability_level: ReliabilityLevel
  retrieved_chunks: RetrievedChunk[]
}

export function listConversations(
  courseId: number,
): AxiosPromise<ConversationListResult> {
  return request.get('/conversations', { params: { course_id: courseId } })
}

export function createConversation(
  payload: ConversationPayload,
): AxiosPromise<Conversation> {
  return request.post('/conversations', payload)
}

export function sendMessage(payload: ChatPayload): AxiosPromise<ChatResult> {
  return request.post('/chat', payload)
}

export function getCitations(
  messageId: number,
): AxiosPromise<CitationListResult> {
  return request.get(`/messages/${messageId}/citations`)
}
