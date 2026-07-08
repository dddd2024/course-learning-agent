import axios from 'axios'
import router from '../router'
import { useAuthStore } from '../stores/auth'
import { API_BASE_URL } from '../config/api'

const request = axios.create({
  // One-click-launch fix: use the unified address (default 127.0.0.1) so
  // the browser hits the same host uvicorn binds to. `localhost` could
  // resolve to IPv6 ::1 on Windows and produce a false unreachable.
  baseURL: API_BASE_URL,
  timeout: 15000,
})

request.interceptors.request.use(
  (config) => {
    // Security Task D: read token from the auth store (sessionStorage by
    // default, localStorage only when "记住登录" was chosen) instead of
    // always reading localStorage directly.
    const auth = useAuthStore()
    if (auth.token) {
      config.headers.Authorization = `Bearer ${auth.token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

request.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    if (status === 401) {
      const auth = useAuthStore()
      auth.clearToken()
      // Closure fix Task C2: preserve the current path as redirect so the
      // user returns to the page they were on (e.g. /logs) after logging
      // in. Skip the push if we're already on /login to avoid duplicate
      // navigation warnings.
      const currentPath = router.currentRoute.value.path
      if (currentPath !== '/login') {
        router.push({
          path: '/login',
          query: { redirect: router.currentRoute.value.fullPath },
        })
      }
    }
    // Task A: report non-401 failures to the log center. Skip the report
    // call itself (X-Skip-Error-Report header) to avoid infinite recursion.
    // Dynamic import avoids a circular dependency (errorReport -> logs -> index).
    const skipReport = error.config?.headers?.['X-Skip-Error-Report'] === '1'
    // Logs-endpoint fix Task C1: the log center's OWN endpoints (/logs,
    // /logs/{id}, /logs/{id}/resolve) must never feed their own failures
    // into the pending error-report queue — that created a self-recursing
    // "log center errors enter the log center" loop. The reportErrorLog
    // POST already sets X-Skip-Error-Report, but the GET/resolve calls
    // did not, so a 401/500 on GET /logs spawned a new pending entry
    // describing "GET /logs 请求失败", which then tried to POST /logs…
    const reqUrl = (error.config?.url || '') as string
    const isLogsEndpoint =
      reqUrl === '/logs' ||
      reqUrl.startsWith('/logs/') ||
      reqUrl.includes('/logs?')
    if (!skipReport && !isLogsEndpoint && status !== 401) {
      // Build a diagnostic payload. Avoid sending the request body (may
      // contain secrets); the backend redacts message/technical_detail too.
      const method = (error.config?.method || 'GET').toUpperCase()
      const url = error.config?.url || ''
      const requestPath = url ? `/api/v1${url}` : null
      const hasResponse = !!error.response
      const category = hasResponse ? 'api' : 'network'
      const statusCode = error.response?.status ?? null
      const serverMessage = error.response?.data?.message
      const technicalDetail = hasResponse
        ? `HTTP ${statusCode}`
        : (error.message || 'Network Error')
      const message = serverMessage
        ? `${method} ${url} 请求失败：${serverMessage}`
        : hasResponse
          ? `${method} ${url} 请求失败：服务返回 ${statusCode}`
          : `${method} ${url} 请求失败：无法连接后端（已保存到本地待上报日志，后端恢复并登录后补发）`
      const frontendRoute = router.currentRoute.value.path

      // Fire-and-forget; never let reporting break the original call.
      import('../utils/errorReport')
        .then(({ reportFrontendError }) =>
          reportFrontendError({
            category,
            level: 'error',
            title: '前端接口请求失败',
            message,
            technical_detail: technicalDetail,
            request_path: requestPath,
            frontend_route: frontendRoute,
            status_code: statusCode,
          }),
        )
        .catch(() => {
          // Swallow — reporting is best-effort.
        })
    }
    return Promise.reject(error)
  },
)

export default request
