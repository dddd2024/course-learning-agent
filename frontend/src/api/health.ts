/**
 * Lightweight backend health check (Redo Task D).
 *
 * Uses a bare axios call (NOT the shared `request` instance) so it:
 *  - does not attach the Authorization header (health is public),
 *  - does not trigger the 401 interceptor / error-report interceptor.
 *
 * Returns the parsed health body on success, or throws on failure. The
 * caller (LogsView) only uses this to update the connection-status banner.
 */
import axios from 'axios'

export interface BackendHealth {
  status: string
  app: string
  version: string
}

export async function checkBackendHealth(): Promise<BackendHealth> {
  const resp = await axios.get('http://localhost:8000/api/v1/health', {
    timeout: 5000,
    // Mark so any shared interceptor (defence in depth) skips reporting.
    headers: { 'X-Skip-Error-Report': '1' },
  })
  return resp.data as BackendHealth
}
