/** 统一 API 错误解析：将后端原始错误转换为用户可理解文案，不暴露技术细节。 */

interface ApiErrorResponse {
  response?: {
    status?: number
    data?: { message?: string; detail?: unknown }
  }
  message?: string
  code?: string
}

export type ApiFailureCategory = 'timeout' | 'network' | 'api'

export function classifyApiFailure(err: unknown): ApiFailureCategory {
  const error = err as ApiErrorResponse
  if (error?.response) return 'api'
  return error?.code === 'ECONNABORTED' || /timeout/i.test(error?.message || '')
    ? 'timeout'
    : 'network'
}

/**
 * 解析 axios 错误，返回面向用户的中文提示。
 *
 * - 422 -> 参数不合法
 * - 404 -> 数据不存在或无权访问
 * - 401 -> 登录已过期
 * - 5xx -> 服务异常
 * - 无 response -> 后端不可达（提示后端可能未启动/端口被占用，而非"网络异常"误导用户以为是外网断了）
 *
 * 优先使用后端 `message` 字段（业务异常），其次按状态码归类，最后回退 fallback。
 */
export function parseApiError(err: unknown, fallback = '操作失败，请重试'): string {
  const e = err as ApiErrorResponse
  const status = e?.response?.status

  // 后端 BusinessException 返回 { message }，优先展示
  const serverMessage = e?.response?.data?.message
  if (serverMessage) return serverMessage

  if (status === undefined) {
    // Redo Task C: distinguish backend-unreachable from a real network
    // outage. The report is saved to the local pending queue and replayed
    // after the backend comes back and the user is authenticated.
    const msg = e?.message || ''
    if (e?.code === 'ECONNABORTED' || msg.toLowerCase().includes('timeout')) {
      return '请求超时：后端已连接，但业务处理超过等待时限'
    }
    return '无法连接后端服务，已保存到本地待上报日志，后端恢复并登录后补发'
  }
  switch (status) {
    case 400:
      return '请求参数不合法，请检查输入'
    case 401:
      return '登录已过期，请重新登录'
    case 403:
      return '没有权限执行此操作'
    case 404:
      return '数据不存在或无权访问'
    case 422:
      return '参数不合法，请检查输入'
    default:
      if (status >= 500) return '服务异常，请稍后重试或查看日志中心'
      return fallback
  }
}
