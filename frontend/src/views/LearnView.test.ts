import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createTestingPinia, mockRoute } from '../test/setup'
import LearnView from './LearnView.vue'
import type { Chunk, Material } from '../api/material'
import type { Course } from '../api/course'

// ---------------------------------------------------------------------------
// API mocks
// ---------------------------------------------------------------------------
vi.mock('../api/course', () => ({
  listCourses: vi.fn().mockResolvedValue({
    data: {
      items: [
        {
          id: 1,
          name: '操作系统',
          teacher: '张老师',
          semester: '2024',
          description: '',
          color: '#409eff',
        },
      ] as Course[],
      total: 1,
      page: 1,
      page_size: 100,
    },
  } as any),
}))

vi.mock('../api/material', () => ({
  listMaterials: vi.fn(),
  getChunks: vi.fn(),
  getMaterialPages: vi.fn(),
  getMaterialReadiness: vi.fn().mockResolvedValue({
    data: {
      usable: true,
      reader_mode: 'structured_text',
      blocking_reasons: [],
      file_type: 'txt',
      missing_page_numbers: [],
    },
  }),
  getImageIntegrity: vi.fn().mockResolvedValue({
    data: { status: 'ready', total: 0, ready: 0, missing: 0, expected_pages: 0, ready_pages: 0, missing_pages: 0 },
  }),
  reextractImages: vi.fn(),
  rebuildPageAssets: vi.fn(),
  generateMaterialStudyGuide: vi.fn(),
}))

vi.mock('../api/chat', () => ({
  createConversation: vi.fn(),
  sendMessage: vi.fn(),
}))

vi.mock('../api/knowledge', () => ({
  listKnowledgePoints: vi.fn().mockResolvedValue({ data: { items: [] } } as any),
}))

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
const mockMaterials: Material[] = [
  {
    id: 1,
    public_id: '00000000-0000-4000-8000-000000000001',
    filename: '操作系统讲义.pdf',
    file_type: 'pdf',
    status: 'ready',
    version: 1,
    uploaded_at: '2024-01-01T00:00:00Z',
  },
]

function makeUsefulChunk(id: number): Chunk {
  return {
    id,
    chunk_index: id,
    title: `第${id}章`,
    text: `这是第${id}章的内容，包含了足够的文字长度来通过过滤器。操作系统的核心功能包括进程管理、内存管理、文件系统和设备管理。`,
    page_no: id,
    quality_score: 0.8,
  }
}

function makeNoiseChunk(id: number): Chunk {
  return {
    id,
    chunk_index: id,
    title: '封面',
    text: '短', // text < 40 chars -> filtered out
    page_no: 0,
    quality_score: null,
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('LearnView', () => {
  beforeEach(() => {
    createTestingPinia()
    vi.clearAllMocks()
    mockRoute.params = { id: '1' }
    mockRoute.query = {}
  })

  it('keeps backend-provided short and cited chunks instead of UI filtering them', async () => {
    const { listMaterials, getChunks, getMaterialPages } = await import('../api/material')
    vi.mocked(getMaterialPages).mockResolvedValue({ data: { items: [] } } as any)
    vi.mocked(listMaterials).mockResolvedValue({ data: { items: mockMaterials, total: 1 } } as any)

    // Return 3 chunks: 2 useful + 1 noise -> filteredCount = 1
    vi.mocked(getChunks).mockResolvedValue({
      data: {
        items: [makeUsefulChunk(1), makeUsefulChunk(2), makeNoiseChunk(3)],
        total: 3,
        page: 1,
        page_size: 100,
      },
    } as any)

    const wrapper = mount(LearnView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()
    await flushPromises()

    const html = wrapper.html()

    // Cleaning is a backend contract: a short page is still navigable and
    // may be an evidence source, so the UI must not hide it heuristically.
    expect(html).toContain('短')
    expect(html).not.toContain('已自动过滤')
  })

  it('decorative image toggle works and reloads chunks', async () => {
    const { listMaterials, getChunks, getMaterialPages } = await import('../api/material')
    vi.mocked(getMaterialPages).mockResolvedValue({ data: { items: [] } } as any)
    vi.mocked(listMaterials).mockResolvedValue({ data: { items: mockMaterials, total: 1 } } as any)
    vi.mocked(getChunks).mockResolvedValue({
      data: {
        items: [makeUsefulChunk(1)],
        total: 1,
        page: 1,
        page_size: 100,
      },
    } as any)

    const wrapper = mount(LearnView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()
    await flushPromises()

    // Initial load: include_decorative should be false (default)
    expect(vi.mocked(getChunks)).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ include_decorative: false }),
    )

    // Find the el-switch component and emit update:modelValue to toggle
    const switchComp = wrapper.findComponent({ name: 'ElSwitch' })
    expect(switchComp.exists()).toBe(true)
    switchComp.vm.$emit('update:modelValue', true)
    switchComp.vm.$emit('change', true)
    await flushPromises()
    await flushPromises()

    // After toggle: getChunks should be called with include_decorative: true
    const lastCall = vi.mocked(getChunks).mock.calls[vi.mocked(getChunks).mock.calls.length - 1]
    expect(lastCall).toBeDefined()
    expect(lastCall![1]).toEqual(
      expect.objectContaining({ include_decorative: true }),
    )
  })

  it('does not claim repair success or run image extraction when page rebuild fails', async () => {
    const { listMaterials, getChunks, getMaterialPages, getMaterialReadiness, rebuildPageAssets, reextractImages } = await import('../api/material')
    vi.mocked(listMaterials).mockResolvedValue({ data: { items: mockMaterials, total: 1 } } as any)
    vi.mocked(getChunks).mockResolvedValue({ data: { items: [makeUsefulChunk(1)], total: 1, page: 1, page_size: 100 } } as any)
    vi.mocked(getMaterialPages).mockResolvedValue({ data: { items: [] } } as any)
    vi.mocked(getMaterialReadiness).mockResolvedValue({
      data: { usable: false, reader_mode: 'page', file_type: 'pdf', missing_page_numbers: [1], blocking_reasons: ['page_assets_missing'] },
    } as any)
    vi.mocked(rebuildPageAssets).mockRejectedValue(new Error('render failed'))

    const wrapper = mount(LearnView, { global: { plugins: [createTestingPinia()] } })
    await flushPromises(); await flushPromises(); await flushPromises()
    const repair = wrapper.findAll('button').find((button) => button.text().includes('修复文档预览'))
    expect(repair).toBeDefined()
    await repair!.trigger('click')
    await flushPromises()
    expect(rebuildPageAssets).toHaveBeenCalledWith(1)
    expect(reextractImages).not.toHaveBeenCalled()
  })

  it('continues repair only after a complete rebuild result', async () => {
    const { listMaterials, getChunks, getMaterialPages, getMaterialReadiness, rebuildPageAssets, reextractImages } = await import('../api/material')
    vi.mocked(listMaterials).mockResolvedValue({ data: { items: mockMaterials, total: 1 } } as any)
    vi.mocked(getChunks).mockResolvedValue({ data: { items: [makeUsefulChunk(1)], total: 1, page: 1, page_size: 100 } } as any)
    vi.mocked(getMaterialPages).mockResolvedValue({ data: { items: [] } } as any)
    vi.mocked(getMaterialReadiness).mockResolvedValue({
      data: { usable: false, reader_mode: 'page', file_type: 'pdf', missing_page_numbers: [1], blocking_reasons: ['page_assets_missing'] },
    } as any)
    vi.mocked(rebuildPageAssets).mockResolvedValue({ data: { status: 'ready', expected_pages: 2, ready_pages: 2, missing_pages: 0 } } as any)
    vi.mocked(reextractImages).mockResolvedValue({ data: { status: 'ready', extracted: 1 } } as any)

    const wrapper = mount(LearnView, { global: { plugins: [createTestingPinia()] } })
    await flushPromises(); await flushPromises(); await flushPromises()
    const repair = wrapper.findAll('button').find((button) => button.text().includes('修复文档预览'))
    await repair!.trigger('click')
    await flushPromises(); await flushPromises()
    expect(reextractImages).toHaveBeenCalledWith(1)
  })
})
