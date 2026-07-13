import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createTestingPinia, mockRoute } from '../test/setup'
import QuizView from './QuizView.vue'
import type { Quiz, QuizResult, QuizResultItem } from '../api/quiz'
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

vi.mock('../api/quiz', () => ({
  getQuizzes: vi.fn(),
  createQuiz: vi.fn(),
  deleteQuiz: vi.fn(),
  getQuiz: vi.fn(),
  getQuizResult: vi.fn(),
  submitQuiz: vi.fn(),
  getWeakPoints: vi.fn(),
}))

vi.mock('../api/knowledge', () => ({
  listKnowledgePoints: vi.fn().mockResolvedValue({ data: { items: [] } } as any),
}))

vi.mock('../api/plan', () => ({
  verifyTask: vi.fn(),
}))

vi.mock('../constants/pagination', () => ({
  MAX_PAGE_SIZE: 100,
}))

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
const mockQuiz: Quiz = {
  id: 1,
  course_id: 1,
  title: '操作系统基础测验',
  question_count: 1,
  status: 'submitted',
  score: 80,
  pass_score: 60,
  created_at: '2024-01-01T00:00:00Z',
  items: [
    {
      id: 101,
      question_type: 'short_answer',
      question_text: '请简述操作系统的进程调度算法。',
      options: [],
      explanation: '进程调度算法包括FCFS、SJF、轮转调度等。',
      order_index: 0,
      source_evidence: [{ chunk_id: 55, quote_text: '进程调度是操作系统的核心功能' }],
    },
  ],
}

const mockResultItem: QuizResultItem = {
  id: 101,
  question_text: '请简述操作系统的进程调度算法。',
  question_type: 'short_answer',
  options: [],
  correct_answer: 'FCFS、SJF、轮转调度等',
  user_answer: 'FCFS和轮转调度',
  is_correct: false,
  explanation: '进程调度算法包括FCFS、SJF、轮转调度等。',
  knowledge_point_id: null,
  rubric_feedback: [
    {
      criterion: '提到FCFS',
      met: true,
      keywords: ['FCFS', '先来先服务'],
      hit_keywords: ['FCFS'],
      missing_keywords: [],
      weight: 0.3,
      score: 0.3,
      message: '提到了FCFS调度算法',
      required: true,
    },
    {
      criterion: '提到SJF',
      met: false,
      keywords: ['SJF', '短作业优先'],
      hit_keywords: [],
      missing_keywords: ['SJF', '短作业优先'],
      weight: 0.3,
      score: 0,
      message: '未提到SJF调度算法',
      required: false,
    },
    {
      criterion: '提到轮转调度',
      met: true,
      keywords: ['轮转', 'RR'],
      hit_keywords: ['轮转'],
      missing_keywords: [],
      weight: 0.4,
      score: 0.4,
      message: '提到了轮转调度算法',
      required: true,
    },
  ],
  needs_review: false,
  source_evidence: [{ chunk_id: 55, quote_text: '进程调度是操作系统的核心功能' }],
}

const mockQuizResult: QuizResult = {
  id: 1,
  score: 70,
  total: 100,
  percentage: 70,
  pass_score: 60,
  passed: true,
  items: [mockResultItem],
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('QuizView', () => {
  beforeEach(() => {
    createTestingPinia()
    vi.clearAllMocks()
    mockRoute.params = {}
    mockRoute.query = { quiz_id: '1', course_id: '1' }
  })

  it('quiz submission shows results with rubric feedback', async () => {
    const { getQuizzes, getQuiz, getQuizResult, getWeakPoints } = await import('../api/quiz')
    vi.mocked(getQuizzes).mockResolvedValue({ data: { items: [mockQuiz], total: 1 } } as any)
    vi.mocked(getQuiz).mockResolvedValue({ data: mockQuiz } as any)
    vi.mocked(getQuizResult).mockResolvedValue({ data: mockQuizResult } as any)
    vi.mocked(getWeakPoints).mockResolvedValue({ data: { items: [] } } as any)

    const wrapper = mount(QuizView, {
      global: { plugins: [createTestingPinia()] },
    })

    // Wait for fetchCourses -> fetchQuizzes -> fetchWeakPoints -> openQuiz -> getQuiz -> getQuizResult
    await flushPromises()
    await flushPromises()
    await flushPromises()
    await flushPromises()

    const html = wrapper.html()

    // Rubric feedback section should be visible
    expect(html).toContain('评分要点')
    // Individual criteria should be visible
    expect(html).toContain('提到FCFS')
    expect(html).toContain('提到SJF')
    // User answer and correct answer should be visible
    expect(html).toContain('你的答案')
    expect(html).toContain('FCFS和轮转调度')
    // Correct answer should be shown
    expect(html).toContain('正确答案')
    // The result contract is visible to the learner, not only returned by the API.
    expect(html).toContain('测验通过')
    expect(html).toContain('及格线：60%')
  })

  it('source evidence displayed with chunk reference', async () => {
    const { getQuizzes, getQuiz, getQuizResult, getWeakPoints } = await import('../api/quiz')
    vi.mocked(getQuizzes).mockResolvedValue({ data: { items: [mockQuiz], total: 1 } } as any)
    vi.mocked(getQuiz).mockResolvedValue({ data: mockQuiz } as any)
    vi.mocked(getQuizResult).mockResolvedValue({ data: mockQuizResult } as any)
    vi.mocked(getWeakPoints).mockResolvedValue({ data: { items: [] } } as any)

    const wrapper = mount(QuizView, {
      global: { plugins: [createTestingPinia()] },
    })

    await flushPromises()
    await flushPromises()
    await flushPromises()
    await flushPromises()

    const html = wrapper.html()

    // Source evidence section should be visible
    expect(html).toContain('来源证据')
    // The chunk ID and quote text should be shown
    expect(html).toContain('片段 #55')
    expect(html).toContain('进程调度是操作系统的核心功能')
  })
})
