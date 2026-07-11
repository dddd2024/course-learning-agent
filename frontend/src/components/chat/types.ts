// Shared types for the chat display components.
// Extracted from ChatView.vue as part of the P2 engineering split
// (no behavior change — these are the same interfaces that lived inline).
import type {
  Citation,
  RetrievedChunk,
  ReliabilityLevel,
} from '../../api/chat'

export interface ChatMessage {
  role: 'user' | 'agent'
  content: string
  messageId?: number
  // ISO timestamp of when the message was created/sent. Populated from
  // HistoryMessage.created_at on replay, or new Date().toISOString() for
  // freshly composed messages. Displayed under each bubble by MessageList.
  createdAt?: string
  citations?: Citation[]
  notFound?: boolean
  followUpQuestions?: string[]
  reliabilityLevel?: ReliabilityLevel
  retrievedChunks?: RetrievedChunk[]
  pending?: boolean
  // Marks an agent message as an error/placeholder (e.g. the SSE stream
  // ended without a final event). Used to distinguish interrupted answers
  // from normal completions.
  error?: boolean
  // T05: LLM fallback visibility (mock fallback marker).
  fallbackUsed?: boolean
  fallbackReason?: string | null
  courseId?: number
}

// A single step in the SSE progress timeline.
export interface StreamStep {
  step: string
  status: 'running' | 'done' | 'error'
  message: string
  advice?: string
}

export type { Citation, RetrievedChunk, ReliabilityLevel }
