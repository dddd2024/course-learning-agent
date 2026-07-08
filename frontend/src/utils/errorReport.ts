/**
 * Frontend error reporting utility (Redo Task C).
 *
 * Hardening over the previous version:
 * - 401 from POST /logs no longer drops the pending item (the user may
 *   just need to re-login); the queue is retained for the next flush
 *   after auth is restored.
 * - 60-second same-error dedupe so a flapping endpoint doesn't flood the
 *   queue / log center.
 * - Queue capped at MAX_QUEUE (50); oldest entries are dropped when full.
 * - Exposes `readPendingQueue()` so the log center can render the local
 *   backlog when the backend is unreachable.
 * - Sanitises payload before sending (defence in depth; the backend also
 *   redacts via `app.services.error_logger.redact_sensitive`).
 *
 * Per the log-center design principle: only failures/warnings are reported
 * here. Success flows never call this.
 */
import { reportErrorLog, type FrontendErrorReportPayload } from '../api/logs'

const PENDING_QUEUE_KEY = 'pending_error_reports'
const MAX_QUEUE = 50
const DEDUPE_WINDOW_MS = 60_000

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
export function readPendingQueue(): FrontendErrorReportPayload[] {
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

function signature(p: FrontendErrorReportPayload): string {
  // Dedupe key: same endpoint + same title within the window counts as
  // the same error storm.
  return `${p.title}|${p.request_path || ''}|${p.message}`
}

// Track the last report time per signature to dedupe within 60s.
const recentReports = new Map<string, number>()

function pruneRecentReports(now: number) {
  for (const [key, ts] of recentReports) {
    if (now - ts > DEDUPE_WINDOW_MS) recentReports.delete(key)
  }
}

/**
 * Send a frontend error report to the log center. If the backend is
 * unreachable (no response) OR returns 401 (auth not ready yet), the
 * payload is retained for later replay. 4xx/5xx (other than 401) drop
 * the item to avoid an unbounded queue of malformed reports.
 *
 * Same-signature errors within 60s are deduped to prevent flooding.
 * Additionally, when the backend is unreachable, the pending queue
 * itself is deduped by signature so a flapping endpoint cannot fill
 * the panel with identical /logs errors.
 *
 * Returns true when the report (and any queued backlog) was flushed,
 * false when the backend was unreachable/401 and the payload was queued.
 */
export async function reportFrontendError(
  rawPayload: FrontendErrorReportPayload,
): Promise<boolean> {
  const payload = sanitizePayload(rawPayload)
  const now = Date.now()
  pruneRecentReports(now)
  const sig = signature(payload)
  if (recentReports.has(sig)) {
    // Already reported (or already queued) this signature within the
    // window — skip to avoid flooding. Still keep any existing backlog.
    return readPendingQueue().length === 0
  }

  // Try to flush the backlog alongside the new report.
  const backlog = readPendingQueue()
  const all = [...backlog, payload]
  const stillPending: FrontendErrorReportPayload[] = []
  // Track signatures already retained so we don't queue the same error
  // twice when the backend is down (one-call-per-second flapping would
  // otherwise fill the panel with identical /logs entries).
  const retainedSigs = new Set<string>()

  for (const item of all) {
    const itemSig = signature(item)
    try {
      await reportErrorLog(item)
      recentReports.set(itemSig, Date.now())
    } catch (err) {
      const e = err as { response?: { status?: number } }
      const status = e.response?.status
      if (status === 401) {
        // Auth not ready / expired — keep the item; main.ts will flush
        // again after ensureAuthReady succeeds. Dedupe by signature.
        if (!retainedSigs.has(itemSig)) {
          stillPending.push(item)
          retainedSigs.add(itemSig)
        }
        // Record the signature so the next identical report within 60s
        // is skipped at the top of this function instead of refilling
        // the queue every second.
        recentReports.set(itemSig, Date.now())
      } else if (e.response) {
        // Backend responded with a non-401 4xx/5xx — the report endpoint
        // itself rejected this payload. Drop it to avoid an unbounded
        // queue of malformed reports.
        continue
      } else {
        // No response => network error / backend unreachable. Keep this
        // item in the queue for later replay, deduped by signature.
        if (!retainedSigs.has(itemSig)) {
          stillPending.push(item)
          retainedSigs.add(itemSig)
        }
        recentReports.set(itemSig, Date.now())
      }
    }
  }

  // Enforce the queue cap: drop the OLDEST entries when over the limit.
  let queued = stillPending
  if (queued.length > MAX_QUEUE) {
    queued = queued.slice(queued.length - MAX_QUEUE)
  }
  writeQueue(queued)

  const newPayloadQueued = queued.some(
    (p) =>
      p.message === payload.message &&
      p.title === payload.title &&
      p.request_path === payload.request_path,
  )
  return !newPayloadQueued
}

/**
 * Attempt to flush any pending reports. Safe to call on app boot or after
 * the user re-authenticates. 401 responses retain the queue; other 4xx/5xx
 * drop the offending item.
 */
export async function flushPendingErrorReports(): Promise<void> {
  const backlog = readPendingQueue()
  if (backlog.length === 0) return
  const stillPending: FrontendErrorReportPayload[] = []
  const retainedSigs = new Set<string>()
  for (const item of backlog) {
    const itemSig = signature(item)
    try {
      await reportErrorLog(item)
    } catch (err) {
      const e = err as { response?: { status?: number } }
      const status = e.response?.status
      if (status === 401) {
        // Dedupe by signature so a backlog with duplicate /logs entries
        // (collected before the dedupe fix) collapses to one on replay.
        if (!retainedSigs.has(itemSig)) {
          stillPending.push(item)
          retainedSigs.add(itemSig)
        }
      } else if (e.response) {
        continue
      } else {
        if (!retainedSigs.has(itemSig)) {
          stillPending.push(item)
          retainedSigs.add(itemSig)
        }
      }
    }
  }
  writeQueue(stillPending)
}
