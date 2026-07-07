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
  // Phase 2 Task A: backend-assembled label for capsule display,
  // e.g. "操作系统讲义.pdf · 第 12 页".
  display_label?: string
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

// Phase 2 Task B: SSE event shapes emitted by POST /chat/stream.
export interface ChatStreamEvent {
  event: 'step_started' | 'step_done' | 'step_error' | 'final' | 'message'
  step?: string
  message?: string
  summary?: Record<string, unknown>
  advice?: string
  data?: ChatResult
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

/**
 * Phase 2 Task B: stream chat progress via Server-Sent Events.
 *
 * Uses the native fetch API (axios does not support streaming responses)
 * to POST /chat/stream and parse the SSE event stream incrementally.
 * The ``onEvent`` callback is invoked for every parsed event; the
 * returned promise resolves with the final ChatResult (from the
 * ``final`` event) or rejects on network / HTTP errors.
 */
export async function sendMessageStream(
  payload: ChatPayload,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<ChatResult | null> {
  const token = localStorage.getItem('token')
  // Phase 2 bugfix P2: use a relative URL so the Vite dev-server proxy
  // (or the production reverse proxy) handles routing. The previous
  // hardcoded http://localhost:8000 broke any non-default port.
  const resp = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  })

  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(
      `chat/stream 请求失败 (${resp.status}): ${text || resp.statusText}`,
    )
  }
  if (!resp.body) {
    throw new Error('chat/stream 返回了空响应体')
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let currentEvent = 'message'
  let dataLines: string[] = []
  let finalResult: ChatResult | null = null

  // Parse SSE frames: lines starting with "event:" / "data:" and
  // blank lines that delimit a complete event.
  const flushEvent = () => {
    if (dataLines.length === 0) return
    const dataStr = dataLines.join('\n')
    dataLines = []
    let parsed: unknown
    try {
      parsed = JSON.parse(dataStr)
    } catch {
      parsed = { raw: dataStr }
    }
    const evt: ChatStreamEvent = {
      event: currentEvent as ChatStreamEvent['event'],
      ...(parsed as Record<string, unknown>),
    }
    currentEvent = 'message'
    if (evt.event === 'final' && evt.data) {
      finalResult = evt.data
    }
    onEvent(evt)
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let newlineIdx: number
    while ((newlineIdx = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, newlineIdx).replace(/\r$/, '')
      buffer = buffer.slice(newlineIdx + 1)
      if (line.startsWith('event: ')) {
        currentEvent = line.slice('event: '.length).trim()
      } else if (line.startsWith('data: ')) {
        dataLines.push(line.slice('data: '.length))
      } else if (line.trim() === '') {
        flushEvent()
      }
    }
  }
  // Flush any trailing event that wasn't delimited by a blank line.
  flushEvent()
  return finalResult
}
