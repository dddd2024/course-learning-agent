/**
 * Unified backend API address configuration.
 *
 * One-click-launch fix: the previous code hardcoded `http://localhost:8000`
 * in api/index.ts and api/health.ts, while start_windows.ps1 binds uvicorn
 * to 127.0.0.1. On Windows, `localhost` may resolve to IPv6 ::1 first; if
 * the backend only listens on IPv4 127.0.0.1, the browser gets a false
 * "unreachable" even though the backend is up. Centralising the address
 * here lets us default to 127.0.0.1 and override via VITE_API_BASE_URL.
 *
 * DIAG_HOSTS is used by the log center's launch-chain diagnostics panel
 * to probe both 127.0.0.1 and localhost and surface the difference to
 * the user instead of a bare "服务不可达".
 */

const ENV_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() || ''

/**
 * Base URL for all business API calls. Defaults to 127.0.0.1 to match the
 * uvicorn bind in start_windows.ps1. Override with VITE_API_BASE_URL when
 * the backend runs elsewhere (e.g. remote dev box, tunnel).
 */
export const API_BASE_URL: string =
  ENV_BASE_URL || 'http://127.0.0.1:8000/api/v1'

/**
 * Host portion of API_BASE_URL — used by the diagnostics panel to label
 * the "current" probe and to pick the default host for checkBackendHealth.
 */
export const API_HOST: string = extractHost(API_BASE_URL)

/** Port portion of API_BASE_URL. */
export const API_PORT: number = extractPort(API_BASE_URL)

/**
 * Hosts to probe in the diagnostics panel. Always includes the configured
 * host plus the alternate IPv4/IPv6 hostname so the user can see whether
 * the issue is address resolution vs. backend not running.
 */
export const DIAG_HOSTS: string[] = unique([
  API_HOST,
  '127.0.0.1',
  'localhost',
])

/** Path to the backend dev log shown in the unreachable banner. */
export const BACKEND_LOG_PATH = 'logs/dev-server/backend.log'

/** Path to the launcher script shown in the unreachable banner. */
export const START_SCRIPT_PATH = 'scripts/start_windows.ps1'

function extractHost(url: string): string {
  const m = url.match(/^https?:\/\/([^:/?#]+)/)
  return m ? m[1] : '127.0.0.1'
}

function extractPort(url: string): number {
  const m = url.match(/^https?:\/\/[^:/?#]+:(\d+)/)
  return m ? parseInt(m[1], 10) : 8000
}

function unique<T>(arr: T[]): T[] {
  return Array.from(new Set(arr))
}
