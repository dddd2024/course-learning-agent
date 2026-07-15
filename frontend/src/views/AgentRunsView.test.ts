import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createTestingPinia } from '../test/setup'
import AgentRunsView from './AgentRunsView.vue'
import type { AgentRun, AgentRunDetail, FallbackChainStep } from '../api/audit'

// ---------------------------------------------------------------------------
// API mocks
// ---------------------------------------------------------------------------
vi.mock('../api/audit', () => ({
  getAgentRuns: vi.fn(),
  getAgentRun: vi.fn(),
}))

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
function makeRun(overrides: Partial<AgentRun>): AgentRun {
  return {
    id: 1,
    user_id: 1,
    run_type: 'quiz_generation',
    status: 'success',
    input_summary: null,
    output_summary: null,
    prompt_version: 'v1',
    model_name: 'gpt-4',
    provider: 'openai',
    requested_provider: 'openai',
    requested_model: 'gpt-4',
    actual_provider: 'openai',
    actual_model: 'gpt-4',
    fallback_used: false,
    fallback_reason: null,
    fallback_chain: null,
    evidence_status: null,
    final_status: null,
    config_id: null,
    duration_ms: 5000,
    error_message: null,
    started_at: '2024-01-01T00:00:00Z',
    finished_at: '2024-01-01T00:00:05Z',
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

const fallbackSteps: FallbackChainStep[] = [
  { provider: 'openai', model: 'gpt-4', status: 'failed', reason: 'rate_limit_exceeded' },
  { provider: 'anthropic', model: 'claude-3-sonnet', status: 'success', reason: null },
]

const mockRuns: AgentRun[] = [
  makeRun({ id: 1, status: 'degraded', fallback_used: true, fallback_reason: 'rate_limit', fallback_chain: fallbackSteps }),
  makeRun({ id: 2, status: 'insufficient_evidence', fallback_used: false }),
  makeRun({ id: 3, status: 'failed', error_message: 'API timeout', fallback_used: false }),
  makeRun({ id: 4, status: 'success', fallback_used: false }),
]

const mockDetail: AgentRunDetail = {
  ...mockRuns[0],
  steps: [
    {
      id: 1,
      run_id: 1,
      step_name: 'generate_quiz',
      step_index: 0,
      input_data: null,
      output_data: null,
      duration_ms: 3000,
      status: 'success',
      error_message: null,
      created_at: '2024-01-01T00:00:00Z',
    },
  ],
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('AgentRunsView', () => {
  beforeEach(() => {
    createTestingPinia()
    vi.clearAllMocks()
  })

  it('degraded/insufficient_evidence/failed status labels display correctly', async () => {
    const { getAgentRuns } = await import('../api/audit')
    vi.mocked(getAgentRuns).mockResolvedValue({ data: { items: mockRuns, total: 4 } } as any)

    const wrapper = mount(AgentRunsView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()

    const html = wrapper.html()

    // Status labels should be rendered correctly
    expect(html).toContain('降级')
    expect(html).toContain('证据不足')
    expect(html).toContain('失败')
    expect(html).toContain('成功')

    // Fallback used tag should be visible for degraded run
    expect(html).toContain('降级')
  })

  it('fallback chain shown in detail drawer', async () => {
    const { getAgentRuns, getAgentRun } = await import('../api/audit')
    vi.mocked(getAgentRuns).mockResolvedValue({ data: { items: mockRuns, total: 4 } } as any)
    vi.mocked(getAgentRun).mockResolvedValue({ data: mockDetail } as any)

    const wrapper = mount(AgentRunsView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()

    // Trigger row-click on the first row to open the detail drawer
    const table = wrapper.findComponent({ name: 'ElTable' })
    if (table.exists()) {
      table.vm.$emit('row-click', mockRuns[0])
      await flushPromises()
      await flushPromises()
    }

    const html = wrapper.html()

    // Fallback chain section should be visible
    expect(html).toContain('Fallback Chain')
    // Fallback chain steps should show provider/model
    expect(html).toContain('openai')
    expect(html).toContain('gpt-4')
    expect(html).toContain('anthropic')
    expect(html).toContain('claude-3-sonnet')
    // The fallback reason should be visible
    expect(html).toContain('rate_limit_exceeded')
  })

  it('marks an old unfinished run as possibly interrupted without changing audit data', async () => {
    const { getAgentRuns, getAgentRun } = await import('../api/audit')
    const staleRun = makeRun({
      id: 9,
      status: 'running',
      started_at: '2024-01-01T00:00:00Z',
      finished_at: null,
      duration_ms: null,
    })
    vi.mocked(getAgentRuns).mockResolvedValue({ data: { items: [staleRun], total: 1 } } as any)
    vi.mocked(getAgentRun).mockResolvedValue({ data: { ...staleRun, steps: [] } } as any)

    const wrapper = mount(AgentRunsView, {
      global: { plugins: [createTestingPinia()] },
    })
    await flushPromises()
    expect(wrapper.html()).toContain('疑似中断')

    const table = wrapper.findComponent({ name: 'ElTable' })
    table.vm.$emit('row-click', staleRun)
    await flushPromises()

    expect(wrapper.html()).toContain('服务重启或执行异常')
    expect(staleRun.status).toBe('running')
  })
})
