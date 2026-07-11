import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createTestingPinia, mockRoute, mockRouter } from '../test/setup'
import PlansView from './PlansView.vue'
import { startTask as mockStartTaskFn } from '../api/plan'
import type { PlanResult, PlanSummary, PlanTask } from '../api/plan'
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

vi.mock('../api/plan', () => ({
  listPlans: vi.fn(),
  getPlan: vi.fn(),
  createPlan: vi.fn(),
  deletePlan: vi.fn(),
  updateGoal: vi.fn(),
  updateTask: vi.fn(),
  updateTodo: vi.fn(),
  startTask: vi.fn(),
  verifyTask: vi.fn(),
  overrideTask: vi.fn(),
}))

vi.mock('../constants/pagination', () => ({
  MAX_PAGE_SIZE: 100,
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function makeTask(overrides: Partial<PlanTask> = {}): PlanTask {
  return {
    id: 1,
    goal_id: 1,
    course_id: 1,
    course_name: '操作系统',
    title: '测试任务',
    task_type: 'quiz',
    estimate_minutes: 30,
    priority: 1,
    acceptance: 'score>=60',
    status: 'active',
    target_type: null,
    target_id: null,
    target_spec: null,
    execution_status: 'pending',
    verification_method: null,
    verification_result: null,
    auto_completed_at: null,
    started_at: null,
    completed_at: null,
    last_action_at: null,
    ...overrides,
  }
}

function makePlanResult(tasks: PlanTask[]): PlanResult {
  return {
    goal: {
      id: 1,
      title: '操作系统学习计划',
      deadline: '2024-12-31',
      daily_minutes: 60,
      status: 'active',
    },
    tasks,
    todos: [],
  }
}

const planSummary: PlanSummary = {
  goal: { id: 1, title: '操作系统学习计划', deadline: '2024-12-31', daily_minutes: 60, status: 'active' },
  course_ids: [1],
  course_names: ['操作系统'],
  progress: { tasks_total: 3, tasks_completed: 1, todos_total: 0, todos_completed: 0 },
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('PlansView', () => {
  beforeEach(() => {
    createTestingPinia()
    vi.clearAllMocks()
    vi.mocked(mockStartTaskFn).mockReset()
    mockRoute.params = {}
    mockRoute.query = {}
    mockRouter.push.mockClear()
  })

  it('task start button navigates to quiz page when quiz_id is returned', async () => {
    const tasks = [makeTask({ id: 10, task_type: 'quiz', execution_status: 'pending' })]
    const planResult = makePlanResult(tasks)

    const { listPlans, getPlan } = await import('../api/plan')
    vi.mocked(listPlans).mockResolvedValue({ data: { items: [planSummary], total: 1 } } as any)
    vi.mocked(getPlan).mockResolvedValue({ data: planResult } as any)
    vi.mocked(mockStartTaskFn).mockResolvedValue({
      data: {
        route: '',
        params: {},
        target_id: 42,
        quiz_id: 42,
        target_type: 'quiz',
        execution_status: 'in_progress',
        started_at: '2024-01-01T00:00:00Z',
      },
    } as any)

    const wrapper = mount(PlansView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()

    // Find the "生成测验" button and click it
    const buttons = wrapper.findAll('button')
    const startBtn = buttons.find((b) => b.text().includes('生成测验'))
    expect(startBtn).toBeTruthy()
    await startBtn!.trigger('click')
    await flushPromises()

    // router.push should have been called with the quiz route
    expect(mockRouter.push).toHaveBeenCalledWith({
      path: '/quizzes',
      query: {
        course_id: 1,
        task_id: '10',
        quiz_id: '42',
      },
    })
  })

  it('task status buttons change based on execution_status', async () => {
    const tasks = [
      makeTask({ id: 1, task_type: 'quiz', execution_status: 'pending' }),
      makeTask({ id: 2, task_type: 'learn', execution_status: 'in_progress' }),
      makeTask({ id: 3, task_type: 'quiz', execution_status: 'completed', target_type: 'quiz', target_id: 99 }),
    ]
    const planResult = makePlanResult(tasks)

    const { listPlans, getPlan } = await import('../api/plan')
    vi.mocked(listPlans).mockResolvedValue({ data: { items: [planSummary], total: 1 } } as any)
    vi.mocked(getPlan).mockResolvedValue({ data: planResult } as any)

    const wrapper = mount(PlansView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()

    const html = wrapper.html()

    // Pending quiz task: button label should be "生成测验"
    expect(html).toContain('生成测验')
    // In-progress learn task: button label should be "开始学习"
    expect(html).toContain('开始学习')
    // Completed quiz task: button label should be "查看结果"
    expect(html).toContain('查看结果')

    // Status labels should reflect the execution_status
    expect(html).toContain('待开始')
    expect(html).toContain('进行中')
    expect(html).toContain('已完成')
  })
})
