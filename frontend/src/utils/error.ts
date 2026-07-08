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
    // Task E: 区分网络异常与后端不可达。axios 无 response 通常意味着
    // 请求未到达后端（后端未启动、端口被占用、CORS 拦截），而不是用户
    // 的外网断了。给出更具体的提示，引导用户排查后端或查看日志中心。
    const msg = e?.message || ''
    if (msg.includes('timeout') || msg.toLowerCase().includes('timeout')) {
      return '请求超时，后端响应时间过长，请稍后重试或查看日志中心'
    }
    return '无法连接后端服务，请确认后端已启动或查看日志中心'
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
