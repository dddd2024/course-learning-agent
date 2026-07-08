/**
 * Frontend error reporting utility (Task A).
 *
 * - Sanitises payload before sending (defence in depth; the backend also
 *   redacts via `app.services.error_logger.redact_sensitive`).
 * - Posts to `POST /api/v1/logs` via `reportErrorLog` (marked with
 *   `X-Skip-Error-Report` so the axios error interceptor does not recurse).
 * - When the backend is unreachable (the report call itself fails with no
 *   response), the payload is stashed in `sessionStorage` and replayed on
 *   the next successful report attempt or on app boot.
 *
 * Per the log-center design principle: only failures/warnings are reported
 * here. Success flows never call this.
 */
import { reportErrorLog, type FrontendErrorReportPayload } from '../api/logs'

const PENDING_QUEUE_KEY = 'pending_error_reports'

// --- client-side redaction (defence in depth) ------------------------------
const SENSITIVE_FIELD_RE =
  /(?<![\w-])(api_key|apiKey|password|passwd|token|secret)\s*[=:]\s*[^\s,;]+/gi
const AUTH_BEARER_RE = /(Authorization\s*:\s*Bearer\s+)[^\s,;]+/gi
const SK_RE = /\bsk-[A-Za-z0-9_\-]+/g
const JWT_RE =
  /\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b/g

function sanitizeText(input: string | null | undefined): string | null {
  if (!input) return input ?? null
  let out = input
  out = out.replace(JWT_RE, '<jwt:***>')
  out = out.replace(AUTH_BEARER_RE, '$1***')
  out = out.replace(SK_RE, 'sk-***')
  out = out.replace(SENSITIVE_FIELD_RE, (_m, key) => `${key}=***`)
  return out
}

function sanitizePayload(
  payload: FrontendErrorReportPayload,
): FrontendErrorReportPayload {
  return {
    ...payload,
    message: sanitizeText(payload.message) ?? payload.message,
    technical_detail: sanitizeText(payload.technical_detail),
    // request_path and frontend_route are URLs, not free text — keep as-is.
  }
}

// --- pending queue (sessionStorage) ----------------------------------------
function readQueue(): FrontendErrorReportPayload[] {
  try {
    const raw = sessionStorage.getItem(PENDING_QUEUE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeQueue(items: FrontendErrorReportPayload[]) {
  try {
    if (items.length === 0) {
      sessionStorage.removeItem(PENDING_QUEUE_KEY)
    } else {
      sessionStorage.setItem(PENDING_QUEUE_KEY, JSON.stringify(items))
    }
  } catch {
    // sessionStorage may be full or disabled — fail silently; reporting
    // is best-effort and must never break the app.
  }
}

/**
 * Send a frontend error report to the log center. If the backend is
 * unreachable (the report call rejects with no `response`), the payload
 * is queued in sessionStorage for later replay.
 *
 * Returns true when the report (and any queued backlog) was flushed,
 * false when the backend was unreachable and the payload was queued.
 */
export async function reportFrontendError(
  rawPayload: FrontendErrorReportPayload,
): Promise<boolean> {
  const payload = sanitizePayload(rawPayload)
  // Try to flush the backlog alongside the new report.
  const backlog = readQueue()
  const all = [...backlog, payload]
  const stillPending: FrontendErrorReportPayload[] = []

  for (const item of all) {
    try {
      await reportErrorLog(item)
    } catch (err) {
      const e = err as { response?: unknown }
      if (e.response) {
        // Backend responded (4xx/5xx) — the report endpoint itself is
        // reachable but rejected this payload. Drop it to avoid an
        // unbounded queue of malformed reports.
        continue
      }
      // No response => network error / backend unreachable. Keep this
      // item in the queue for later replay.
      stillPending.push(item)
    }
  }
  writeQueue(stillPending)

  // If the new payload was flushed (not in stillPending) the report
  // succeeded. If it landed in stillPending, the backend was unreachable.
  const newPayloadQueued = stillPending.some(
    (p) => p === payload || (p.message === payload.message && p.title === payload.title && p.request_path === payload.request_path),
  )
  return !newPayloadQueued
}

/**
 * Attempt to flush any pending reports left from a previous offline
 * session. Safe to call on app boot.
 */
export async function flushPendingErrorReports(): Promise<void> {
  const backlog = readQueue()
  if (backlog.length === 0) return
  const stillPending: FrontendErrorReportPayload[] = []
  for (const item of backlog) {
    try {
      await reportErrorLog(item)
    } catch (err) {
      const e = err as { response?: unknown }
      if (e.response) continue
      stillPending.push(item)
    }
  }
  writeQueue(stillPending)
}
