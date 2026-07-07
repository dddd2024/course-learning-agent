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
  citations?: Citation[]
  notFound?: boolean
  followUpQuestions?: string[]
  reliabilityLevel?: ReliabilityLevel
  retrievedChunks?: RetrievedChunk[]
  pending?: boolean
  // T05: LLM fallback visibility (mock fallback marker).
  fallbackUsed?: boolean
  fallbackReason?: string | null
}

// A single step in the SSE progress timeline.
export interface StreamStep {
  step: string
  status: 'running' | 'done' | 'error'
  message: string
  advice?: string
}

export type { Citation, RetrievedChunk, ReliabilityLevel }
