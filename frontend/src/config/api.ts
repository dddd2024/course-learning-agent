/**
 * Unified backend API address configuration.
 *
 * ERR_NETWORK fix (same-origin proxy): API_BASE_URL now defaults to the
 * relative path '/api/v1'. In dev, the Vite dev-server proxy forwards
 * /api -> http://127.0.0.1:8000, so the browser only ever makes
 * same-origin requests to http://127.0.0.1:5173/api/v1/... — the
 * Authorization header no longer triggers a cross-origin preflight,
 * which was the root cause of /logs-with-token returning ERR_NETWORK.
 *
 * Set VITE_API_BASE_URL to force a cross-origin absolute URL (e.g. when
 * targeting a remote backend that is NOT behind the Vite proxy). In that
 * mode the browser will make cross-origin requests again and CORS must
 * be configured on the backend.
 *
 * DIAG_HOSTS / API_HOST / API_PORT are still derived for the log
 * center's diagnostics panel, which probes the backend DIRECTLY (bypassing
 * the proxy) to tell address-resolution failure from backend-down. When
 * API_BASE_URL is relative, they fall back to 127.0.0.1:8000 which matches
 * the uvicorn bind in start_windows.ps1.
 */

const ENV_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() || ''

/**
 * Base URL for all business API calls. Defaults to '/api/v1' (same-origin
 * via the Vite dev-server proxy). Override with VITE_API_BASE_URL when
 * the backend is NOT behind the proxy (remote dev box, tunnel, etc.).
 */
export const API_BASE_URL: string = ENV_BASE_URL || '/api/v1'

/**
 * The backend origin that the Vite dev-server proxy forwards /api to.
 * Used by the LogsView diagnostics panel so the user can see "browser
 * request is same-origin /api/v1, Vite proxies to 127.0.0.1:8000".
 */
export const BACKEND_PROXY_TARGET = 'http://127.0.0.1:8000'

/**
 * Public material-image base. Keep it same-origin when the API uses the
 * development proxy, and derive it from an explicitly configured backend
 * origin for remote deployments.
 */
export const UPLOAD_BASE_URL: string = ENV_BASE_URL
  ? `${ENV_BASE_URL.replace(/\/api\/v1\/?$/, '')}/uploads`
  : '/uploads'

/**
 * Whether API_BASE_URL is a relative path (same-origin via proxy) vs.
 * an absolute URL (cross-origin). Used to decide whether to show the
 * "same-origin proxy" hint in the diagnostics panel.
 */
export const IS_SAME_ORIGIN: boolean = !ENV_BASE_URL

/**
 * Host portion of the backend, used by the diagnostics panel to label
 * the "current" probe and to pick the default host for checkBackendHealth.
 * Falls back to 127.0.0.1 when API_BASE_URL is relative.
 */
export const API_HOST: string = extractHost(API_BASE_URL)

/** Backend port. Falls back to 8000 when API_BASE_URL is relative. */
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
