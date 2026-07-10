<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowLeft,
  ChatDotRound,
  Delete,
  Edit,
  MoreFilled,
  Plus,
  Promotion,
  Search,
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

const messages = ref<ChatMessage[]>([])
const inputText = ref('')
const sending = ref(false)

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
        activeConversationId.value = null
        messages.value = []
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

async function selectConversation(conv: Conversation) {
  if (activeConversationId.value === conv.id) return
  activeConversationId.value = conv.id
  messages.value = []
  resetStreamState()
  statusExpanded.value = false
  // T04: load conversation history so switching/reloading shows prior Q&A.
  try {
    const { data } = await listMessages(conv.id)
    messages.value = data.items.map(historyToChatMessage)
    await nextTick()
    scrollToBottom()
  } catch (err) {
    // 读历史失败时不清空已选状态，只提示；用户仍可发新消息。
    ElMessage.error(parseApiError(err, '读取历史失败'))
  }
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
  if (sending.value) return

  messages.value.push({
    role: 'user',
    content: question,
    createdAt: new Date().toISOString(),
  })
  inputText.value = ''
  await runChat(question)
}

// Core SSE chat flow: push a pending agent bubble and stream the answer.
// Shared by handleSend (new question) and handleRegenerate (re-ask the
// previous question). Assumes a conversation is already selected.
async function runChat(question: string) {
  if (!activeConversationId.value) return

  const pendingIndex =
    messages.value.push({
      role: 'agent',
      content: '正在思考...',
      pending: true,
      courseId: courseId.value,
      createdAt: new Date().toISOString(),
    }) - 1
  sending.value = true

  // Phase 2 Task B: expand the status panel and reset step state.
  resetStreamState()
  statusExpanded.value = true
  await nextTick()
  scrollToBottom()

  const payload = {
    course_id: courseId.value,
    conversation_id: activeConversationId.value,
    question,
  }

  try {
    // Prefer SSE streaming for live progress; fall back to the sync
    // POST /chat endpoint ONLY if the stream connection failed before
    // any event was received. Once events have arrived the user message
    // is already persisted server-side, so a sync retry would duplicate it.
    let result: ChatResult | null = null
    let receivedAnyEvent = false
    try {
      result = await sendMessageStream(payload, (evt) => {
        receivedAnyEvent = true
        handleStreamEvent(evt)
      })
    } catch (streamErr) {
      if (!receivedAnyEvent) {
        // No events received → safe to retry via sync endpoint.
        const { data } = await sendMessage(payload)
        result = data
      } else {
        // Events already arrived → the user message is persisted; do
        // NOT retry via /chat (would duplicate the message). Surface
        // the error instead.
        throw streamErr
      }
    }
    if (result) {
      applyChatResult(pendingIndex, result)
      // Collapse the panel on success unless an error was signalled.
      if (!streamError.value) {
        statusExpanded.value = false
      }
    } else if (streamError.value) {
      // A step_error ended the stream with no final result.
      messages.value.splice(pendingIndex, 1)
      ElMessage.error(streamError.value)
    }
  } catch (err) {
    messages.value.splice(pendingIndex, 1)
    ElMessage.error(parseApiError(err, '发送问题失败'))
  } finally {
    sending.value = false
    await nextTick()
    scrollToBottom()
  }
}

// Re-generate an AI answer: locate the user question that preceded the
// given agent message, drop the old answer, and re-run the SSE flow.
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

  // Remove the old AI answer before re-asking.
  if (msgIndex !== -1) {
    messages.value.splice(msgIndex, 1)
  }

  await runChat(question)
}

function applyChatResult(pendingIndex: number, result: ChatResult): void {
  const msg = messages.value[pendingIndex]
  if (!msg) return
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
  await fetchCourse()
  if (!course.value) return
  await fetchConversations()
  if (conversations.value.length > 0) {
    await selectConversation(conversations.value[0])
  }
})
</script>

<template>
  <div v-loading="courseLoading" class="chat-page">
    <div class="chat-header">
      <el-button :icon="ArrowLeft" @click="goBack">返回课程详情</el-button>
      <div v-if="course" class="course-brief">
        <span class="course-name">{{ course.name }}</span>
        <span v-if="course.teacher" class="course-meta">教师：{{ course.teacher }}</span>
      </div>
    </div>

    <div class="chat-body">
      <div class="chat-sidebar">
        <div class="sidebar-header">
          <span class="sidebar-title">对话列表</span>
          <el-button
            type="primary"
            size="small"
            :icon="Plus"
            :loading="creating"
            @click="handleCreateConversation"
          >
            新建
          </el-button>
        </div>
        <div class="sidebar-search">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索对话..."
            :prefix-icon="Search"
            clearable
            size="small"
            class="conv-search"
          />
        </div>
        <div v-loading="conversationsLoading" class="conversation-list">
          <div
            v-for="conv in filteredConversations"
            :key="conv.id"
            class="conversation-item"
            :class="{ active: conv.id === activeConversationId }"
            @click="selectConversation(conv)"
          >
            <el-icon class="conv-icon"><ChatDotRound /></el-icon>
            <div class="conv-info">
              <div class="conv-title">{{ conv.title }}</div>
              <div class="conv-time">
                {{ new Date(conv.created_at).toLocaleString() }}
              </div>
            </div>
            <span class="conv-actions" @click.stop>
              <el-dropdown
                trigger="click"
                placement="bottom-end"
                @command="(cmd: string | number | object) => handleConversationCommand(cmd, conv)"
              >
                <el-icon class="conv-actions-trigger"><MoreFilled /></el-icon>
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
          v-if="activeConversationId && messages.length > 0"
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
          <div
            v-if="showScrollBottom"
            class="scroll-bottom-btn"
            @click="scrollToBottomSmooth"
          >
            <el-icon :size="20"><ArrowDown /></el-icon>
          </div>
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
            :disabled="sending"
            @keydown.enter.exact.prevent="handleSend"
          />
          <el-button
            type="primary"
            :icon="Promotion"
            :loading="sending"
            :disabled="!inputText.trim()"
            @click="handleSend"
          >
            发送
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
  gap: 8px;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
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
  padding: 2px;
  border-radius: 4px;
  outline: none;
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
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  z-index: 10;
  transition: opacity 0.3s, transform 0.3s;
}

.scroll-bottom-btn:hover {
  transform: scale(1.1);
  background: #66b1ff;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
