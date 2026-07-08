/**
 * Lightweight backend health check (one-click-launch fix).
 *
 * Uses bare axios (NOT the shared `request` instance) so it:
 *  - does not attach the Authorization header (health is public),
 *  - does not trigger the 401 interceptor / error-report interceptor.
 *
 * `checkBackendHealth()` probes the configured API_BASE_URL host.
 * `checkBackendHealthByHost(host)` probes a specific host (used by the
 * log center's diagnostics panel to compare 127.0.0.1 vs localhost and
 * tell the user whether the issue is address resolution vs. backend down).
 */
import axios from 'axios'
import { API_BASE_URL, API_PORT } from '../config/api'

export interface BackendHealth {
  status: string
  app: string
  version: string
}

export interface HostHealthResult {
  host: string
  ok: boolean
  health?: BackendHealth
  error?: string
}

function healthUrlForHost(host: string): string {
  return `http://${host}:${API_PORT}/api/v1/health`
}

export async function checkBackendHealth(): Promise<BackendHealth> {
  const resp = await axios.get(`${API_BASE_URL}/health`, {
    timeout: 5000,
    // Mark so any shared interceptor (defence in depth) skips reporting.
    headers: { 'X-Skip-Error-Report': '1' },
  })
  return resp.data as BackendHealth
}

/**
 * Probe a specific host (e.g. '127.0.0.1' or 'localhost') and return a
 * structured result instead of throwing. Used by the diagnostics panel
 * to compare address resolution vs. backend reachability.
 */
export async function checkBackendHealthByHost(
  host: string,
): Promise<HostHealthResult> {
  try {
    const resp = await axios.get(healthUrlForHost(host), {
      timeout: 5000,
      headers: { 'X-Skip-Error-Report': '1' },
    })
    return { host, ok: true, health: resp.data as BackendHealth }
  } catch (err) {
    const e = err as { message?: string }
    return { host, ok: false, error: e.message || 'unreachable' }
  }
}
