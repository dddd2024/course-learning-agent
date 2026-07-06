/** 统一 API 错误解析：将后端原始错误转换为用户可理解文案，不暴露技术细节。 */

interface ApiErrorResponse {
  response?: {
    status?: number
    data?: { message?: string; detail?: unknown }
  }
  message?: string
}

/**
 * 解析 axios 错误，返回面向用户的中文提示。
 *
 * - 422 -> 参数不合法
 * - 404 -> 数据不存在或无权访问
 * - 401 -> 登录已过期
 * - 5xx -> 服务异常
 * - 无 response -> 网络异常
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
    return '网络异常，请检查网络连接'
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
      if (status >= 500) return '服务异常，请稍后重试'
      return fallback
  }
}
