import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createTestingPinia, mockRoute } from '../test/setup'
import ChatView from './ChatView.vue'
import MessageList from '../components/chat/MessageList.vue'
import type { ChatMessage } from '../components/chat/types'
import type { Citation } from '../api/chat'

// ---------------------------------------------------------------------------
// API mocks
// ---------------------------------------------------------------------------
vi.mock('../api/course', () => ({
  getCourse: vi.fn().mockResolvedValue({
    data: {
      id: 1,
      name: '测试课程',
      teacher: '张老师',
      semester: '2024',
      description: '测试课程描述',
      color: '#409eff',
    },
  } as any),
}))

vi.mock('../api/chat', () => ({
  listConversations: vi.fn().mockResolvedValue({
    data: {
      items: [
        {
          id: 1,
          course_id: 1,
          title: '测试对话',
          created_at: '2024-01-01T00:00:00Z',
        },
      ],
      total: 1,
    },
  } as any),
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  getCitations: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } } as any),
  listMessages: vi.fn().mockResolvedValue({
    data: {
      items: [
        {
          id: 1,
          role: 'user',
          content: '什么是操作系统？',
          citations: [],
          created_at: '2024-01-01T00:00:00Z',
          answer_json: null,
        },
        {
          id: 2,
          role: 'assistant',
          content: '操作系统是管理计算机硬件和软件资源的系统软件。',
          citations: [],
          created_at: '2024-01-01T00:00:01Z',
          answer_json: null,
        },
      ],
      total: 2,
    },
  } as any),
  renameConversation: vi.fn(),
  sendMessage: vi.fn(),
  sendMessageStream: vi.fn(),
}))

vi.mock('../api/material', () => ({
  getChunk: vi.fn().mockResolvedValue({
    data: {
      chunk_id: 1,
      material_id: 1,
      material_name: 'test.pdf',
      title: 'test',
      page_no: 1,
      text: 'test text',
    },
  } as any),
}))

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('ChatView', () => {
  beforeEach(() => {
    createTestingPinia()
    vi.clearAllMocks()
    mockRoute.params = { id: '1' }
    mockRoute.query = {}
  })

  it('shows evidence insufficient message when no supported citations', async () => {
    const wrapper = mount(ChatView, {
      global: { plugins: [createTestingPinia()] },
    })

    // Wait for fetchCourse, fetchConversations, selectConversation, loadConversationHistory
    await flushPromises()
    await flushPromises()
    await flushPromises()

    const html = wrapper.html()
    // When there are no citations, the "本次回答未找到直接资料依据" message
    // should be displayed for the assistant message.
    expect(html).toContain('本次回答未找到直接资料依据')
  })

  it('does not show weak citations as formal/verified', async () => {
    // Mount MessageList directly with citations that have support_status='weak'.
    // This tests the citation display behaviour that ChatView delegates to
    // MessageList.
    const weakCitations: Citation[] = [
      {
        chunk_id: 10,
        material_name: '讲义.pdf',
        page_no: 5,
        quote_text: '操作系统的基本概念',
        confidence: 0.3,
        support_status: 'weak',
      },
    ]

    const messages: ChatMessage[] = [
      {
        role: 'agent',
        content: '操作系统是管理硬件的系统软件。',
        citations: weakCitations,
        pending: false,
      },
    ]

    const wrapper = mount(MessageList, {
      props: { messages },
    })

    const html = wrapper.html()

    // Weak citations should trigger the info alert, NOT the
    // "本次回答未找到直接资料依据" message.
    expect(html).toContain('部分资料片段仅与回答相关')
    // The no-citation message should NOT appear when weak citations exist.
    expect(html).not.toContain('本次回答未找到直接资料依据')
    // Citation capsules should still show the citation count.
    expect(html).toContain('引用资料 (1)')
  })

  it('shows formal citation count when verified citations exist', async () => {
    const verifiedCitations: Citation[] = [
      {
        chunk_id: 20,
        material_name: '教材.pdf',
        page_no: 12,
        quote_text: '进程管理是操作系统的核心功能',
        confidence: 0.9,
        support_status: 'verified',
      },
    ]

    const messages: ChatMessage[] = [
      {
        role: 'agent',
        content: '进程管理是操作系统的核心功能。',
        citations: verifiedCitations,
        pending: false,
      },
    ]

    const wrapper = mount(MessageList, {
      props: { messages },
    })

    const html = wrapper.html()
    // Verified citations should show capsules.
    expect(html).toContain('引用资料 (1)')
    // Verified citations should NOT trigger the weak-citation alert.
    expect(html).not.toContain('部分资料片段仅与回答相关')
  })
})
