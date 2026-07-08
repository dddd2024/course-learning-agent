/**
 * /logs three-layer diagnostics (closure fix Task B).
 *
 * When the log center shows "/logs 不可达" but /health is green, the user
 * needs to know WHICH layer failed:
 *   1. backend process (health, no auth)  — is the server alive?
 *   2. /logs route without auth           — does the route exist + is CORS
 *                                           baseline reachable? (401 = yes)
 *   3. /logs route with current token     — is the user authed/authorized?
 *
 * All three use bare axios (NOT the shared `request` instance) so they
 * bypass the Authorization-attaching request interceptor AND the 401 /
 * error-report response interceptors. This prevents the diagnostics
 * themselves from spawning pending error reports or triggering redirect
 * loops.
 */
import axios from 'axios'
import { API_BASE_URL } from '../config/api'

export interface ProbeResult {
  /** Whether the request succeeded (2xx) OR returned 401 (route reachable). */
  reachable: boolean
  /** HTTP status code, or null when the browser got no response. */
  statusCode: number | null
  /** HTTP status text, or null. */
  statusText: string | null
  /** axios error code (e.g. ERR_NETWORK, ERR_FAILED, ERR_CANCELED). */
  axiosCode: string | null
  /** axios error message. */
  axiosMessage: string | null
  /** Backend `message` field from the response body, if any. */
  serverMessage: string | null
  /** Backend `detail` field from the response body, if any. */
  serverDetail: string | null
}

function emptyResult(): ProbeResult {
  return {
    reachable: false,
    statusCode: null,
    statusText: null,
    axiosCode: null,
    axiosMessage: null,
    serverMessage: null,
    serverDetail: null,
  }
}

/**
 * Layer 1: GET /health with no Authorization. Confirms the backend process
 * is alive and identifies itself as course-learning-agent.
 */
export async function probeHealthBare(): Promise<ProbeResult> {
  const result = emptyResult()
  try {
    const resp = await axios.get(`${API_BASE_URL}/health`, {
      timeout: 5000,
      headers: { 'X-Skip-Error-Report': '1' },
    })
    result.reachable = true
    result.statusCode = resp.status
    result.statusText = resp.statusText
    return result
  } catch (err) {
    return fillError(result, err)
  }
}

/**
 * Layer 2: GET /logs with NO Authorization header. We expect a 401 — that
 * proves the /logs route exists, CORS preflight passed, and the request
 * reached the backend. A 401 here is a GOOD sign (reachable=true). A
 * no-response here indicates CORS / network interception.
 */
export async function probeLogsNoToken(): Promise<ProbeResult> {
  const result = emptyResult()
  try {
    const resp = await axios.get(`${API_BASE_URL}/logs`, {
      timeout: 5000,
      params: { page: 1, page_size: 1 },
      headers: { 'X-Skip-Error-Report': '1' },
    })
    // 2xx with no auth is unexpected but still "reachable".
    result.reachable = true
    result.statusCode = resp.status
    result.statusText = resp.statusText
    return result
  } catch (err) {
    const e = err as {
      response?: { status?: number; statusText?: string; data?: { message?: string; detail?: unknown } }
      code?: string
      message?: string
    }
    if (e.response) {
      // Got an HTTP response — the route is reachable. 401 is the expected
      // result for an unauthenticated /logs probe.
      result.reachable = true
      result.statusCode = e.response.status ?? null
      result.statusText = e.response.statusText ?? null
      result.serverMessage = e.response.data?.message ?? null
      const d = e.response.data?.detail
      result.serverDetail =
        typeof d === 'string' ? d : d != null ? JSON.stringify(d) : null
      return result
    }
    return fillError(result, err)
  }
}

/**
 * Layer 3: GET /logs WITH the current Authorization token. Classifies the
 * result as reachable (2xx or 401/403) vs. browser-no-response.
 */
export async function probeLogsWithToken(token: string): Promise<ProbeResult> {
  const result = emptyResult()
  try {
    const resp = await axios.get(`${API_BASE_URL}/logs`, {
      timeout: 5000,
      params: { page: 1, page_size: 1 },
      headers: {
        Authorization: `Bearer ${token}`,
        'X-Skip-Error-Report': '1',
      },
    })
    result.reachable = true
    result.statusCode = resp.status
    result.statusText = resp.statusText
    return result
  } catch (err) {
    const e = err as {
      response?: { status?: number; statusText?: string; data?: { message?: string; detail?: unknown } }
      code?: string
      message?: string
    }
    if (e.response) {
      result.reachable = true
      result.statusCode = e.response.status ?? null
      result.statusText = e.response.statusText ?? null
      result.serverMessage = e.response.data?.message ?? null
      const d = e.response.data?.detail
      result.serverDetail =
        typeof d === 'string' ? d : d != null ? JSON.stringify(d) : null
      return result
    }
    return fillError(result, err)
  }
}

function fillError(result: ProbeResult, err: unknown): ProbeResult {
  const e = err as { code?: string; message?: string }
  result.axiosCode = e.code ?? null
  result.axiosMessage = e.message ?? null
  return result
}

/**
 * Run all three layers and return the combined result. Used by the
 * LogsView diagnostics panel.
 */
export interface LogsDiagnosticsResult {
  health: ProbeResult
  logsNoToken: ProbeResult
  logsWithToken: ProbeResult
  checkedAt: string
}

export async function runLogsDiagnostics(
  token: string | null,
): Promise<LogsDiagnosticsResult> {
  const [health, logsNoToken, logsWithToken] = await Promise.all([
    probeHealthBare(),
    probeLogsNoToken(),
    token ? probeLogsWithToken(token) : Promise.resolve(emptyResult()),
  ])
  return {
    health,
    logsNoToken,
    logsWithToken,
    checkedAt: new Date().toLocaleTimeString(),
  }
}
