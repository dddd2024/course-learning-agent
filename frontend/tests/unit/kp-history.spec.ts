import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createTestingPinia } from '../../src/test/setup'

// ---------------------------------------------------------------------------
// Mock the axios request instance so we can intercept all API calls.
// This lets the REAL API functions (getKPGenerations, listKnowledgePoints,
// etc.) be exercised while controlling their return values.
// ---------------------------------------------------------------------------
vi.mock('../../src/api/index', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

import request from '../../src/api/index'
import { getKPGenerations } from '../../src/api/knowledge'
import { API_BASE_URL } from '../../src/config/api'
import { ElMessageBox } from 'element-plus'
import OutlineView from '../../src/views/OutlineView.vue'
import type { Course } from '../../src/api/course'

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
const mockCourse: Course = {
  id: 1,
  name: '数据结构',
  teacher: '张老师',
  semester: '2024春',
  description: '数据结构课程',
  color: '#409eff',
}

const mockKnowledgePoints = [
  {
    id: 1,
    title: '数据结构基础',
    summary: '基本数据结构概念',
    importance: 5,
    source_chunk_ids: [],
    exam_style: '选择题',
    review_action: '复习第一章',
    status: 'active',
  },
]

const mockGenerations = [
  { generation: 2, status: 'current', count: 15, created_at: '2024-01-02T10:00:00Z' },
  { generation: 1, status: 'archived', count: 12, created_at: '2024-01-01T10:00:00Z' },
]

// ---------------------------------------------------------------------------
// Helper: configure mock request for standard mount scenario
// ---------------------------------------------------------------------------
function setupMockRequest(opts?: {
  generations?: typeof mockGenerations
}) {
  vi.mocked(request.get).mockImplementation(((url: string) => {
    if (url === '/courses/1') {
      return Promise.resolve({ data: mockCourse })
    }
    if (url === '/courses/1/knowledge-points') {
      return Promise.resolve({
        data: { items: mockKnowledgePoints, total: mockKnowledgePoints.length },
      })
    }
    if (url === '/courses/1/knowledge-points/generations') {
      return Promise.resolve({ data: opts?.generations ?? mockGenerations })
    }
    return Promise.resolve({ data: {} })
  }) as any)
  vi.mocked(request.post).mockResolvedValue({ data: {} } as any)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('KP Generation History', () => {
  beforeEach(() => {
    createTestingPinia()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // -------------------------------------------------------------------------
  // API function tests
  // -------------------------------------------------------------------------
  describe('getKPGenerations API function', () => {
    it('exists in the knowledge API module', () => {
      expect(getKPGenerations).toBeDefined()
      expect(typeof getKPGenerations).toBe('function')
    })

    it('calls GET /api/v1/courses/{courseId}/knowledge-points/generations', async () => {
      vi.mocked(request.get).mockResolvedValue({ data: [] } as any)

      await getKPGenerations(42)

      // The function calls request.get with the path. The axios instance's
      // baseURL ('/api/v1') is prepended automatically, forming the full
      // endpoint /api/v1/courses/42/knowledge-points/generations.
      expect(request.get).toHaveBeenCalledWith(
        '/courses/42/knowledge-points/generations',
      )
      // Verify the base URL prefix that completes the full endpoint.
      expect(API_BASE_URL).toBe('/api/v1')
    })
  })

  // -------------------------------------------------------------------------
  // OutlineView component tests
  // -------------------------------------------------------------------------
  describe('OutlineView generation history', () => {
    it('renders a generation history section', async () => {
      setupMockRequest()

      const wrapper = mount(OutlineView, {
        global: { plugins: [createTestingPinia()] },
      })

      await flushPromises()
      await flushPromises()
      await flushPromises()

      const html = wrapper.html()
      // The generation history section should be present
      expect(html).toContain('生成历史')
      // Generation version numbers should be rendered
      expect(html).toContain('第 2 版')
      // Knowledge-point count should be rendered
      expect(html).toContain('15')
    })

    it('regenerate warning text contains "归档" not "删除"', async () => {
      setupMockRequest()

      // Spy on ElMessageBox.confirm and make it reject (user clicks cancel)
      // so we can capture the warning message without proceeding.
      const confirmSpy = vi
        .spyOn(ElMessageBox, 'confirm')
        .mockRejectedValue(new Error('cancel'))

      try {
        const wrapper = mount(OutlineView, {
          global: { plugins: [createTestingPinia()] },
        })

        await flushPromises()
        await flushPromises()
        await flushPromises()

        // Find and click the regenerate button
        const buttons = wrapper.findAll('button')
        const regenerateBtn = buttons.find((b) =>
          b.text().includes('重新生成'),
        )
        expect(regenerateBtn).toBeTruthy()
        await regenerateBtn!.trigger('click')
        await flushPromises()

        // ElMessageBox.confirm should have been called
        expect(confirmSpy).toHaveBeenCalled()
        const message = confirmSpy.mock.calls[0][0] as string
        // Warning must say "归档" (archive), NOT "删除" (delete)
        expect(message).toContain('归档')
        expect(message).not.toContain('删除')
      } finally {
        confirmSpy.mockRestore()
      }
    })
  })
})
