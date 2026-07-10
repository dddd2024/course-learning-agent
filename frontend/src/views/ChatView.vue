<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowLeft,
  ChatDotRound,
  Close,
  Delete,
  Edit,
  Menu,
  MoreFilled,
  Plus,
  Promotion,
  Search,
  VideoPause,
} from '@element-plus/icons-vue'
import { getCourse, type Course } from '../api/course'
import {
  createConversation,
  deleteConversation,
  getCitations,
  listConversations,
  listMessages,
  renameConversation,
  sendMessage,
  sendMessageStream,
  type ChatResult,
  type ChatStreamEvent,
  type Citation,
  type Conversation,
  type HistoryMessage,
  type RetrievedChunk,
} from '../api/chat'
import { getChunk, type ChunkDetail } from '../api/material'
import { parseApiError } from '../utils/error'
import { formatLocalDateTime } from '@/utils/datetime'
import type { ChatMessage, StreamStep } from '../components/chat/types'
import MessageList from '../components/chat/MessageList.vue'
import SseStatusPanel from '../components/chat/SseStatusPanel.vue'
import EvidenceDrawer from '../components/chat/EvidenceDrawer.vue'
import EmptyState from '../components/common/EmptyState.vue'

const route = useRoute()
const router = useRouter()

const courseId = computed(() => Number(route.params.id))

const course = ref<Course | null>(null)
const courseLoading = ref(false)

const conversations = ref<Conversation[]>([])
const conversationsLoading = ref(false)
const creating = ref(false)
const activeConversationId = ref<number | null>(null)
const conversationHistoryLoading = ref(false)
const conversationLoadError = ref<string | null>(null)
let conversationLoadRequestId = 0

const isMobileViewport = ref(false)
const mobileConversationOpen = ref(false)
const mobileSidebarRef = ref<HTMLElement | null>(null)
const mobileSidebarOpenerRef = ref<HTMLButtonElement | null>(null)
let mobileMediaQuery: MediaQueryList | null = null

// Sidebar conversation search: filters the list by title (case-insensitive).
// Empty keyword shows all conversations.
const searchKeyword = ref('')
const filteredConversations = computed(() => {
  if (!searchKeyword.value.trim()) return conversations.value
  const kw = searchKeyword.value.toLowerCase()
  return conversations.value.filter((c) =>
    c.title.toLowerCase().includes(kw),
  )
})

function openConversationDrawer() {
  mobileConversationOpen.value = true
  void nextTick(() => mobileSidebarRef.value?.focus())
}

function closeConversationDrawer(restoreFocus = true) {
  if (!mobileConversationOpen.value) return
  mobileConversationOpen.value = false
  if (restoreFocus) {
    void nextTick(() => mobileSidebarOpenerRef.value?.focus())
  }
}

function handleMobileSidebarKeydown(event: KeyboardEvent) {
  if (!isMobileViewport.value || !mobileConversationOpen.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeConversationDrawer()
    return
  }
  if (event.key !== 'Tab' || !mobileSidebarRef.value) return

  const focusable = Array.from(
    mobileSidebarRef.value.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.hasAttribute('inert'))
  if (focusable.length === 0) return

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function cancelChatForConversationChange() {
  if (!abortController.value) return
  chatRequestSequence += 1
  abortController.value.abort()
  abortController.value = null
  sending.value = false
}

const messages = ref<ChatMessage[]>([])
const inputText = ref('')
const sending = ref(false)
// AbortController for stopping an in-flight SSE stream. When non-null
// a generation is running and the stop button is shown.
const abortController = ref<AbortController | null>(null)
let chatRequestSequence = 0

const messageListRef = ref<HTMLElement | null>(null)
// Scroll-to-bottom button visibility: shown when the user has scrolled
// up more than ~200px from the bottom of the chat area.
const showScrollBottom = ref(false)

const drawerVisible = ref(false)
const drawerCitation = ref<Citation | null>(null)
const drawerMessage = ref<ChatMessage | null>(null)
const drawerLoading = ref(false)
// Phase 2 bugfix P0-2: full chunk text fetched from /chunks/{id} so the
// drawer can show the complete context around a citation's quote_text.
const drawerChunk = ref<ChunkDetail | null>(null)

// Phase 2 Task B: SSE status-panel state.
// - streamSteps: ordered list of steps for the in-flight request.
// - streamError: when set, the panel expands to show advice.
// - statusExpanded: manual collapse control (auto-expands on send/error).
const streamSteps = ref<StreamStep[]>([])
const streamError = ref<string | null>(null)
const streamAdvice = ref<string | null>(null)
const statusExpanded = ref(false)

// Phase 2 Task B: human-readable label for an SSE step name. Kept here
// because it is used to set the default step message during event
// handling (business state), not just for display.
function stepLabel(step: string | undefined): string {
  switch (step) {
    case 'retrieve':
      return '检索资料'
    case 'generate':
      return '生成回答'
    case 'citation':
      return '整理引用'
    default:
      return step || '处理中'
  }
}

function resetStreamState() {
  streamSteps.value = []
  streamError.value = null
  streamAdvice.value = null
}

function handleStreamEvent(evt: ChatStreamEvent) {
  if (evt.event === 'step_started' && evt.step) {
    const existing = streamSteps.value.find((s) => s.step === evt.step)
    if (existing) {
      existing.status = 'running'
      existing.message = evt.message || existing.message
    } else {
      streamSteps.value.push({
        step: evt.step,
        status: 'running',
        message: evt.message || stepLabel(evt.step),
      })
    }
  } else if (evt.event === 'step_done' && evt.step) {
    const existing = streamSteps.value.find((s) => s.step === evt.step)
    if (existing) {
      existing.status = 'done'
      if (evt.message) existing.message = evt.message
    }
  } else if (evt.event === 'step_error') {
    const existing = streamSteps.value.find((s) => s.step === evt.step)
    if (existing) {
      existing.status = 'error'
      if (evt.message) existing.message = evt.message
    } else if (evt.step) {
      streamSteps.value.push({
        step: evt.step,
        status: 'error',
        message: evt.message || stepLabel(evt.step),
      })
    }
    streamError.value = evt.message || '处理失败'
    streamAdvice.value = evt.advice || null
    statusExpanded.value = true
  }
}

async function fetchCourse() {
  if (!courseId.value) {
    ElMessage.error('课程 ID 无效')
    router.push('/courses')
    return
  }
  courseLoading.value = true
  try {
    const { data } = await getCourse(courseId.value)
    course.value = data
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取课程详情失败'))
    router.push('/courses')
  } finally {
    courseLoading.value = false
  }
}

async function fetchConversations() {
  if (!courseId.value) return
  conversationsLoading.value = true
  try {
    const { data } = await listConversations(courseId.value)
    conversations.value = data.items
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取对话列表失败'))
  } finally {
    conversationsLoading.value = false
  }
}

async function handleCreateConversation() {
  if (!courseId.value) return
  creating.value = true
  try {
    const now = new Date()
    const title = `新对话 ${now.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })}`
    const { data } = await createConversation({
      course_id: courseId.value,
      title,
    })
    conversations.value.unshift(data)
    await selectConversation(data)
  } catch (err) {
    ElMessage.error(parseApiError(err, '创建对话失败'))
  } finally {
    creating.value = false
  }
}

// Rename a conversation via ElMessageBox.prompt → renameConversation.
// The conversation list is refreshed in place (replace the edited item)
// so the sidebar stays sorted and the active selection is preserved.
async function handleRenameConversation(conv: Conversation) {
  let value: string
  try {
    const res = await ElMessageBox.prompt('请输入新的对话名称', '重命名对话', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: conv.title ?? '',
      inputValidator: (v: string) => {
        const t = (v ?? '').trim()
        if (!t) return '名称不能为空'
        if (t.length > 255) return '名称不能超过 255 个字符'
        return true
      },
    })
    value = res.value
  } catch (action) {
    // User cancelled or closed the prompt — ignore silently.
    if (action === 'cancel' || action === 'close') return
    throw action
  }
  const title = value.trim()
  if (!title || title === conv.title) return
  try {
    const { data } = await renameConversation(conv.id, title)
    const idx = conversations.value.findIndex((c) => c.id === conv.id)
    if (idx !== -1) conversations.value[idx] = data
    ElMessage.success('已重命名')
  } catch (err) {
    ElMessage.error(parseApiError(err, '重命名失败'))
  }
}

// Delete a conversation after confirmation. If the deleted conversation
// was the active one, select the first remaining conversation or fall
// back to the empty state when none are left.
async function handleDeleteConversation(conv: Conversation) {
  try {
    await ElMessageBox.confirm(
      `确定删除对话「${conv.title}」吗？删除后无法恢复。`,
      '删除对话',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return // user cancelled
  }
  try {
    await deleteConversation(conv.id)
    const idx = conversations.value.findIndex((c) => c.id === conv.id)
    if (idx !== -1) conversations.value.splice(idx, 1)
    if (activeConversationId.value === conv.id) {
      if (conversations.value.length > 0) {
        await selectConversation(conversations.value[0])
      } else {
        conversationLoadRequestId += 1
        activeConversationId.value = null
        messages.value = []
        conversationHistoryLoading.value = false
        conversationLoadError.value = null
        resetStreamState()
      }
    }
    ElMessage.success('已删除')
  } catch (err) {
    ElMessage.error(parseApiError(err, '删除失败'))
  }
}

// Dispatch el-dropdown commands for a conversation item. The command
// type mirrors el-dropdown's emitted value (string | number | object).
function handleConversationCommand(
  command: string | number | object,
  conv: Conversation,
) {
  const cmd = String(command)
  if (cmd === 'rename') {
    void handleRenameConversation(conv)
  } else if (cmd === 'delete') {
    void handleDeleteConversation(conv)
  }
}

// T04: convert a history message from the backend into the ChatMessage
// shape used by the message list. Assistant messages parse answer_json
// (the full structured LLM result) to restore citations, follow-ups,
// not_found, and reliability level. If parsing fails we fall back to
// the citations table rows attached to the message.
function historyToChatMessage(m: HistoryMessage): ChatMessage {
  let citations: Citation[] = []
  let followUpQuestions: string[] = []
  let notFound = false
  let reliabilityLevel: ChatMessage['reliabilityLevel']
  let retrievedChunks: RetrievedChunk[] = []
  let fallbackUsed = false
  let fallbackReason: string | null = null

  if (m.answer_json) {
    try {
      const parsed = JSON.parse(m.answer_json) as Record<string, unknown>
      const parsedCites = (parsed.citations ?? []) as Array<Record<string, unknown>>
      citations = parsedCites.map((c, i): Citation => ({
        chunk_id: Number(c.chunk_id ?? 0),
        material_name:
          (c.material_name as string | undefined) ??
          m.citations[i]?.material_name ??
          '',
        page_no: Number(
          (c.page_no as number | null | undefined) ??
            m.citations[i]?.page_no ??
            0,
        ),
        quote_text: (c.quote_text as string | undefined) ?? '',
        confidence: Number(c.confidence ?? 0),
        display_label:
          (c.display_label as string | null | undefined) ??
          m.citations[i]?.display_label ??
          undefined,
      }))
      followUpQuestions = (parsed.follow_up_questions as string[]) ?? []
      notFound = Boolean(parsed.not_found)
      reliabilityLevel = parsed.reliability_level as ChatMessage['reliabilityLevel']
      retrievedChunks = (parsed.retrieved_chunks as RetrievedChunk[]) ?? []
      fallbackUsed = Boolean(parsed.fallback_used)
      fallbackReason = (parsed.fallback_reason as string | null) ?? null
    } catch {
      // answer_json corrupted — fall back to citations table rows.
      citations = m.citations.map((c): Citation => ({
        chunk_id: c.chunk_id,
        material_name: c.material_name ?? '',
        page_no: Number(c.page_no ?? 0),
        quote_text: c.quote_text ?? '',
        confidence: 0,
        display_label: c.display_label ?? undefined,
      }))
    }
  }

  return {
    role: m.role === 'user' ? 'user' : 'agent',
    content: m.content ?? '',
    messageId: m.id,
    createdAt: m.created_at,
    citations,
    followUpQuestions,
    notFound,
    reliabilityLevel,
    retrievedChunks,
    fallbackUsed,
    fallbackReason,
    courseId: courseId.value,
    pending: false,
  }
}

async function loadConversationHistory(conversationId: number) {
  const requestId = ++conversationLoadRequestId
  conversationHistoryLoading.value = true
  conversationLoadError.value = null
  try {
    const { data } = await listMessages(conversationId)
    if (
      requestId !== conversationLoadRequestId ||
      activeConversationId.value !== conversationId
    ) {
      return
    }
    messages.value = data.items.map(historyToChatMessage)
    await nextTick()
    scrollToBottom()
  } catch (err) {
    if (
      requestId !== conversationLoadRequestId ||
      activeConversationId.value !== conversationId
    ) {
      return
    }
    conversationLoadError.value = parseApiError(err, '读取历史失败')
  } finally {
    if (
      requestId === conversationLoadRequestId &&
      activeConversationId.value === conversationId
    ) {
      conversationHistoryLoading.value = false
    }
  }
}

async function selectConversation(conv: Conversation) {
  closeConversationDrawer(false)
  if (activeConversationId.value === conv.id) {
    if (conversationLoadError.value) {
      await loadConversationHistory(conv.id)
    }
    return
  }

  cancelChatForConversationChange()
  activeConversationId.value = conv.id
  messages.value = []
  resetStreamState()
  statusExpanded.value = false
  await loadConversationHistory(conv.id)
}

async function retryConversationLoad() {
  if (!activeConversationId.value || conversationHistoryLoading.value) return
  if (sending.value) {
    ElMessage.warning('请先停止当前回答，再重试加载历史')
    return
  }
  await loadConversationHistory(activeConversationId.value)
}

async function handleSend() {
  const question = inputText.value.trim()
  if (!question) {
    ElMessage.warning('请输入问题')
    return
  }
  if (!activeConversationId.value) {
    ElMessage.warning('请先选择或创建对话')
    return
  }
  if (conversationHistoryLoading.value) {
    ElMessage.info('正在加载对话历史，请稍候再发送')
    return
  }
  if (sending.value) return

  messages.value.push({
    role: 'user',
    content: question,
    createdAt: new Date().toISOString(),
  })
  inputText.value = ''
  await runChat(question)
}

// Abort the in-flight SSE stream. The fetch inside sendMessageStream
// will reject with an AbortError, which runChat's catch block handles
// gracefully by keeping any partial content already received.
function stopGeneration() {
  if (abortController.value) {
    abortController.value.abort()
  }
}

// Core SSE chat flow. Each run captures its conversation and pending message,
// so late events cannot overwrite another conversation after the user switches.
async function runChat(question: string) {
  if (!activeConversationId.value) return

  const conversationId = activeConversationId.value
  const requestId = ++chatRequestSequence
  const pendingMessage: ChatMessage = {
    role: 'agent',
    content: '正在思考...',
    pending: true,
    courseId: courseId.value,
    createdAt: new Date().toISOString(),
  }
  messages.value.push(pendingMessage)
  sending.value = true
  const controller = new AbortController()
  abortController.value = controller

  const isCurrentRun = () =>
    requestId === chatRequestSequence &&
    activeConversationId.value === conversationId &&
    messages.value.includes(pendingMessage)
  const removePendingMessage = () => {
    const index = messages.value.indexOf(pendingMessage)
    if (index !== -1) messages.value.splice(index, 1)
  }
  const markStopped = () => {
    if (!isCurrentRun()) return
    pendingMessage.pending = false
    if (!pendingMessage.content || pendingMessage.content === '正在思考...') {
      pendingMessage.content = '（已停止生成）'
    }
  }

  resetStreamState()
  statusExpanded.value = true
  await nextTick()
  scrollToBottom()

  const payload = {
    course_id: courseId.value,
    conversation_id: conversationId,
    question,
  }

  try {
    // Fall back to the synchronous endpoint only before the stream emits an
    // event. Once an event arrives, retrying could persist the question twice.
    let result: ChatResult | null = null
    let receivedAnyEvent = false
    try {
      result = await sendMessageStream(
        payload,
        (evt) => {
          receivedAnyEvent = true
          if (isCurrentRun()) handleStreamEvent(evt)
        },
        controller.signal,
      )
    } catch (streamErr) {
      if (streamErr instanceof Error && streamErr.name === 'AbortError') {
        markStopped()
      } else if (!receivedAnyEvent) {
        const { data } = await sendMessage(payload)
        result = data
      } else {
        throw streamErr
      }
    }
    if (result && isCurrentRun()) {
      applyChatResult(pendingMessage, result)
      if (!streamError.value) statusExpanded.value = false
    } else if (streamError.value && isCurrentRun()) {
      removePendingMessage()
      ElMessage.error(streamError.value)
    } else if (isCurrentRun()) {
      // SSE stream ended without a final event and without an error.
      // This happens when the connection is interrupted (proxy timeout,
      // network drop) after step events but before the final event.
      pendingMessage.pending = false
      pendingMessage.content = '回答生成中断，请重新提问或重试。'
      pendingMessage.error = true
      ElMessage.warning('回答未完整返回，请重试')
    }
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      markStopped()
    } else if (isCurrentRun()) {
      removePendingMessage()
      ElMessage.error(parseApiError(err, '发送问题失败'))
    }
  } finally {
    if (requestId === chatRequestSequence) {
      abortController.value = null
      sending.value = false
      if (activeConversationId.value === conversationId) {
        await nextTick()
        scrollToBottom()
      }
    }
  }
}

// There is no backend endpoint that can replace an answer in place. Preserve
// the original and explicitly confirm a visible new request instead.
async function handleRegenerate(msg: ChatMessage) {
  if (sending.value) return
  if (!activeConversationId.value) {
    ElMessage.warning('请先选择或创建对话')
    return
  }

  const msgIndex = messages.value.indexOf(msg)
  let question = ''
  if (msgIndex !== -1) {
    // Walk backwards to the most recent user message before this answer.
    for (let i = msgIndex - 1; i >= 0; i--) {
      if (messages.value[i].role === 'user') {
        question = messages.value[i].content
        break
      }
    }
  }
  if (!question) {
    ElMessage.warning('未找到对应的提问内容')
    return
  }

  const conversationId = activeConversationId.value
  try {
    await ElMessageBox.confirm(
      '当前版本不支持原地替换回答。继续后会保留现有回答，并将原问题作为一条新提问再次发送。',
      '作为新问题再次提问',
      {
        type: 'info',
        confirmButtonText: '保留回答并再次提问',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  if (
    activeConversationId.value !== conversationId ||
    !messages.value.includes(msg)
  ) {
    ElMessage.info('对话已切换，未发送新问题')
    return
  }
  messages.value.push({
    role: 'user',
    content: question,
    createdAt: new Date().toISOString(),
  })
  await runChat(question)
}

function applyChatResult(msg: ChatMessage, result: ChatResult): void {
  msg.content = result.answer || '(无回答内容)'
  msg.messageId = result.message_id
  msg.citations = result.citations ?? []
  msg.notFound = result.not_found
  msg.followUpQuestions = result.follow_up_questions ?? []
  msg.reliabilityLevel = result.reliability_level
  msg.retrievedChunks = result.retrieved_chunks ?? []
  // T05: surface LLM fallback state on the message bubble.
  msg.fallbackUsed = result.fallback_used ?? false
  msg.fallbackReason = result.fallback_reason ?? null
  msg.pending = false
}

// Instant scroll to the latest message. Used after sending a question
// and after a response arrives so the chat always lands on the newest
// content without a jarring animated scroll mid-stream.
function scrollToBottom() {
  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight
  }
}

// Smooth scroll to the latest message, used by the floating
// scroll-to-bottom button so the user sees the transition.
function scrollToBottomSmooth() {
  if (messageListRef.value) {
    messageListRef.value.scrollTo({
      top: messageListRef.value.scrollHeight,
      behavior: 'smooth',
    })
  }
}

// Toggle the scroll-to-bottom button based on how far the user is from
// the bottom of the chat area. The button appears once they scroll up
// more than ~200px and hides again when they return near the bottom.
function handleChatScroll() {
  const el = messageListRef.value
  if (!el) return
  const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  showScrollBottom.value = distFromBottom > 200
}

async function openCitationDrawer(citation: Citation, msg: ChatMessage) {
  drawerCitation.value = citation
  drawerMessage.value = msg
  drawerChunk.value = null
  drawerVisible.value = true
  drawerLoading.value = true
  try {
    // Fetch the full chunk text for evidence display + highlighting.
    const { data: chunk } = await getChunk(citation.chunk_id)
    drawerChunk.value = chunk
    // Also try to enrich with the persisted citation (may carry a
    // longer quote_text than the inline one).
    if (msg.messageId) {
      try {
        const { data } = await getCitations(msg.messageId)
        const full = data.items.find((c) => c.chunk_id === citation.chunk_id)
        if (full) {
          drawerCitation.value = full
        }
      } catch {
        // 静默失败，使用内联数据
      }
    }
  } catch {
    // If the chunk fetch fails (e.g. cross-user), fall back to the
    // inline quote_text only — no full context, no highlight.
    drawerChunk.value = null
  } finally {
    drawerLoading.value = false
  }
}

function openRetrievalDrawer(msg: ChatMessage) {
  drawerCitation.value = null
  drawerMessage.value = msg
  drawerVisible.value = true
}

// Phase 2 Task B: the current running step (if any) for the header chip.
const currentRunningStep = computed(() =>
  streamSteps.value.find((s) => s.status === 'running'),
)

function toggleStatusPanel() {
  statusExpanded.value = !statusExpanded.value
}

function handleFollowUp(question: string) {
  inputText.value = question
  drawerVisible.value = false
  handleSend()
}

function goBack() {
  router.push(`/courses/${courseId.value}`)
}

onMounted(async () => {
  mobileMediaQuery = window.matchMedia('(max-width: 768px)')
  isMobileViewport.value = mobileMediaQuery.matches
  mobileMediaQuery.addEventListener('change', handleMobileViewportChange)

  await fetchCourse()
  if (!course.value) return
  await fetchConversations()
  if (conversations.value.length > 0) {
    await selectConversation(conversations.value[0])
  }
})

function handleMobileViewportChange(event: MediaQueryListEvent) {
  isMobileViewport.value = event.matches
  if (!event.matches) mobileConversationOpen.value = false
}

onBeforeUnmount(() => {
  conversationLoadRequestId += 1
  chatRequestSequence += 1
  abortController.value?.abort()
  mobileMediaQuery?.removeEventListener('change', handleMobileViewportChange)
})
</script>

<template>
  <div v-loading="courseLoading" class="chat-page">
    <div class="chat-header">
      <button
        ref="mobileSidebarOpenerRef"
        type="button"
        class="mobile-conversation-trigger"
        aria-controls="conversation-sidebar"
        :aria-expanded="mobileConversationOpen"
        @click="openConversationDrawer"
      >
        <el-icon><Menu /></el-icon>
        <span>对话</span>
      </button>
      <el-button :icon="ArrowLeft" @click="goBack">返回课程详情</el-button>
      <div v-if="course" class="course-brief">
        <span class="course-name">{{ course.name }}</span>
        <span v-if="course.teacher" class="course-meta">教师：{{ course.teacher }}</span>
      </div>
    </div>

    <div class="chat-body">
      <transition name="sidebar-overlay">
        <div
          v-if="isMobileViewport && mobileConversationOpen"
          class="chat-sidebar-overlay"
          aria-hidden="true"
          @click="closeConversationDrawer()"
        />
      </transition>
      <div
        id="conversation-sidebar"
        ref="mobileSidebarRef"
        class="chat-sidebar"
        :class="{ 'chat-sidebar--open': mobileConversationOpen }"
        :role="isMobileViewport ? 'dialog' : 'navigation'"
        :aria-modal="isMobileViewport ? 'true' : undefined"
        aria-label="对话列表"
        :aria-hidden="isMobileViewport && !mobileConversationOpen"
        :inert="isMobileViewport && !mobileConversationOpen"
        tabindex="-1"
        @keydown="handleMobileSidebarKeydown"
      >
        <div class="sidebar-header">
          <span class="sidebar-title">对话列表</span>
          <div class="sidebar-header-actions">
            <el-button
              type="primary"
              size="small"
              :icon="Plus"
              :loading="creating"
              @click="handleCreateConversation"
            >
              新建
            </el-button>
            <button
              type="button"
              class="mobile-sidebar-close"
              aria-label="关闭对话列表"
              @click="closeConversationDrawer()"
            >
              <el-icon><Close /></el-icon>
            </button>
          </div>
        </div>
        <div class="sidebar-search">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索对话..."
            :prefix-icon="Search"
            clearable
            size="small"
            class="conv-search"
            aria-label="搜索对话"
          />
        </div>
        <div
          v-loading="conversationsLoading"
          class="conversation-list"
          role="list"
          aria-label="可用对话"
        >
          <div
            v-for="conv in filteredConversations"
            :key="conv.id"
            class="conversation-item"
            :class="{ active: conv.id === activeConversationId }"
            role="listitem"
          >
            <button
              type="button"
              class="conversation-select"
              :aria-current="conv.id === activeConversationId ? 'true' : undefined"
              @click="selectConversation(conv)"
            >
              <el-icon class="conv-icon"><ChatDotRound /></el-icon>
              <div class="conv-info">
                <div class="conv-title">{{ conv.title }}</div>
                <div class="conv-time">
                  {{ formatLocalDateTime(conv.created_at) }}
                </div>
              </div>
            </button>
            <span class="conv-actions" @click.stop>
              <el-dropdown
                trigger="click"
                placement="bottom-end"
                @command="(cmd: string | number | object) => handleConversationCommand(cmd, conv)"
              >
                <el-button
                  text
                  circle
                  size="small"
                  class="conv-actions-trigger"
                  :icon="MoreFilled"
                  :aria-label="`管理对话：${conv.title}`"
                />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="rename" :icon="Edit">
                      重命名
                    </el-dropdown-item>
                    <el-dropdown-item command="delete" :icon="Delete" divided>
                      删除
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </span>
          </div>
          <EmptyState
            v-if="!conversationsLoading && conversations.length === 0"
            title="还没有对话"
            description="开始提问创建新对话"
          />
          <EmptyState
            v-else-if="!conversationsLoading && filteredConversations.length === 0"
            title="未找到匹配的对话"
            description="试试其他关键词"
          />
        </div>
      </div>

      <div class="chat-main">
        <div
          v-if="activeConversationId && conversationHistoryLoading"
          class="conversation-load-state"
          aria-live="polite"
          aria-label="正在加载对话历史"
        >
          <el-skeleton :rows="5" animated />
        </div>

        <div
          v-else-if="activeConversationId && conversationLoadError"
          class="conversation-load-state conversation-load-error"
          role="alert"
        >
          <el-alert
            title="对话历史加载失败"
            :description="conversationLoadError"
            type="error"
            :closable="false"
            show-icon
          />
          <el-button
            type="primary"
            :loading="conversationHistoryLoading"
            :disabled="sending"
            @click="retryConversationLoad"
          >
            重试加载
          </el-button>
        </div>

        <div
          v-else-if="activeConversationId && messages.length > 0"
          ref="messageListRef"
          class="message-list"
          @scroll="handleChatScroll"
        >
          <MessageList
            :messages="messages"
            @open-citation="openCitationDrawer"
            @open-retrieval="openRetrievalDrawer"
            @follow-up="handleFollowUp"
            @regenerate="handleRegenerate"
          />
        </div>

        <div v-else class="chat-empty">
          <EmptyState
            title="开始新的对话"
            :action-text="activeConversationId ? undefined : '创建对话'"
            @action="handleCreateConversation"
          />
        </div>

        <!-- Floating scroll-to-bottom button: appears when the user has
             scrolled up away from the latest message. -->
        <transition name="fade">
          <button
            v-if="showScrollBottom"
            type="button"
            class="scroll-bottom-btn"
            aria-label="滚动到最新消息"
            @click="scrollToBottomSmooth"
          >
            <el-icon :size="20"><ArrowDown /></el-icon>
          </button>
        </transition>

        <SseStatusPanel
          v-if="activeConversationId"
          :steps="streamSteps"
          :error="streamError"
          :advice="streamAdvice"
          :expanded="statusExpanded"
          :running-step="currentRunningStep"
          @toggle="toggleStatusPanel"
        />

        <div v-if="activeConversationId" class="chat-input">
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="2"
            placeholder="输入问题，回车发送（Shift+回车换行）"
            resize="none"
            aria-label="输入问题"
            :disabled="sending || conversationHistoryLoading"
            @keydown.enter.exact.prevent="handleSend"
          />
          <el-button
            type="primary"
            :icon="Promotion"
            :loading="sending"
            :disabled="!inputText.trim() || conversationHistoryLoading"
            aria-label="发送问题"
            @click="handleSend"
          >
            发送
          </el-button>
          <el-button
            v-if="sending"
            type="danger"
            :icon="VideoPause"
            aria-label="停止生成回答"
            @click="stopGeneration"
          >
            停止
          </el-button>
        </div>
      </div>
    </div>

    <EvidenceDrawer
      v-model:visible="drawerVisible"
      :loading="drawerLoading"
      :citation="drawerCitation"
      :message="drawerMessage"
      :chunk="drawerChunk"
      @follow-up="handleFollowUp"
    />
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 100px);
  background: #fff;
  border-radius: 4px;
  overflow: hidden;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  flex-shrink: 0;
}

.mobile-conversation-trigger,
.mobile-sidebar-close {
  display: none;
  border: 0;
  background: transparent;
  color: #303133;
  cursor: pointer;
}

.chat-sidebar-overlay {
  display: none;
}

.course-brief {
  display: flex;
  align-items: center;
  gap: 12px;
}

.course-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.course-meta {
  font-size: 13px;
  color: #909399;
}

.chat-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.chat-sidebar {
  width: 260px;
  border-right: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  background: #fff;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f2f5;
}

.sidebar-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.sidebar-header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sidebar-search {
  padding: 8px 12px;
  border-bottom: 1px solid #f0f2f5;
}

.conv-search {
  margin-bottom: 0;
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px 4px 2px 0;
  border-radius: 6px;
  transition: background 0.2s;
}

.conversation-select {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 8px 8px 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.conversation-item:hover {
  background: #f5f7fa;
}

.conversation-item.active {
  background: #ecf5ff;
}

.conv-icon {
  color: #909399;
  flex-shrink: 0;
  font-size: 16px;
}

.conversation-item.active .conv-icon {
  color: #409eff;
}

.conv-info {
  flex: 1;
  min-width: 0;
}

.conv-title {
  font-size: 13px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-time {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

/* Per-conversation rename/delete menu. Hidden by default and revealed
   on item hover (or when the item is active) to keep the list calm. */
.conv-actions {
  flex-shrink: 0;
  margin-left: auto;
  opacity: 0;
  transition: opacity 0.2s;
}

.conversation-item:hover .conv-actions,
.conversation-item.active .conv-actions {
  opacity: 1;
}

.conv-actions-trigger {
  cursor: pointer;
  color: #909399;
  font-size: 16px;
  width: 30px;
  height: 30px;
}

.conv-actions-trigger:hover {
  color: #409eff;
  background: #ecf5ff;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.chat-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.conversation-load-state {
  flex: 1;
  padding: 32px;
  overflow-y: auto;
}

.conversation-load-error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 16px;
  max-width: 640px;
  width: 100%;
  margin: 0 auto;
}

.chat-input {
  padding: 12px 16px;
  border-top: 1px solid #ebeef5;
  display: flex;
  gap: 8px;
  align-items: flex-end;
  flex-shrink: 0;
}

.chat-input :deep(.el-textarea) {
  flex: 1;
}

/* Floating scroll-to-bottom button. Shown when the user scrolls up
   away from the latest message; clicking it smooth-scrolls back. */
.scroll-bottom-btn {
  position: absolute;
  bottom: 80px;
  right: 24px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border: 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  z-index: 10;
  transition: opacity 0.3s, transform 0.3s;
}

.scroll-bottom-btn:hover {
  transform: scale(1.1);
  background: #66b1ff;
}

.mobile-conversation-trigger:focus-visible,
.mobile-sidebar-close:focus-visible,
.conversation-select:focus-visible,
.scroll-bottom-btn:focus-visible,
.conv-actions-trigger:focus-visible {
  outline: 3px solid rgba(64, 158, 255, 0.45);
  outline-offset: 2px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Responsive: on narrow screens the sidebar becomes an off-canvas
   drawer that slides in from the left. The main chat area takes the
   full width. */
@media (max-width: 768px) {
  .chat-header {
    flex-wrap: wrap;
    gap: 8px;
    padding: 10px 12px;
  }

  .mobile-conversation-trigger {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    min-height: 32px;
    padding: 5px 10px;
    border: 1px solid #dcdfe6;
    border-radius: 4px;
    background: #fff;
    font-size: 14px;
  }

  .course-brief {
    order: 3;
    flex-basis: 100%;
    min-width: 0;
    flex-wrap: wrap;
    gap: 4px 10px;
  }

  .course-name {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .chat-sidebar-overlay {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: rgba(0, 0, 0, 0.45);
  }

  .chat-sidebar {
    position: fixed;
    left: 0;
    top: 0;
    width: min(86vw, 320px);
    height: 100vh;
    z-index: 1001;
    transform: translateX(-100%);
    transition: transform 0.3s;
    box-shadow: 8px 0 24px rgba(0, 0, 0, 0.16);
    outline: none;
  }

  .chat-sidebar--open {
    transform: translateX(0);
  }

  .mobile-sidebar-close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 4px;
    font-size: 18px;
  }

  .mobile-sidebar-close:hover {
    background: #f5f7fa;
  }

  .conv-actions {
    opacity: 1;
  }

  .chat-main {
    width: 100%;
  }

  .message-list {
    padding: 12px;
  }

  .conversation-load-state {
    padding: 20px 16px;
  }

  .chat-input {
    flex-wrap: wrap;
    padding: 10px 12px;
  }

  .chat-input :deep(.el-textarea) {
    flex: 1 0 100%;
  }

  .chat-input > .el-button {
    margin-left: 0;
  }

  .chat-input > .el-button:first-of-type {
    margin-left: auto;
  }

  .scroll-bottom-btn {
    right: 16px;
    bottom: 128px;
  }
}

.sidebar-overlay-enter-active,
.sidebar-overlay-leave-active {
  transition: opacity 0.2s ease;
}

.sidebar-overlay-enter-from,
.sidebar-overlay-leave-to {
  opacity: 0;
}
</style>
