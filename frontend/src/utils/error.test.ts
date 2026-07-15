import { describe, expect, it } from 'vitest'
import { classifyApiFailure, parseApiError } from './error'

describe('API error classification', () => {
  it('classifies Axios timeout separately from an unreachable backend', () => {
    const timeout = { code: 'ECONNABORTED', message: 'timeout of 30000ms exceeded' }
    expect(classifyApiFailure(timeout)).toBe('timeout')
    expect(parseApiError(timeout)).toContain('后端已连接')
    expect(classifyApiFailure({ message: 'Network Error' })).toBe('network')
  })

  it('preserves the backend business message for API responses', () => {
    const error = { response: { status: 422, data: { message: '课程暂无知识点' } } }
    expect(classifyApiFailure(error)).toBe('api')
    expect(parseApiError(error)).toBe('课程暂无知识点')
  })
})
