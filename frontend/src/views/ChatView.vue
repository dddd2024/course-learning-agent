<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  ChatDotRound,
  Plus,
  Promotion,
} from '@element-plus/icons-vue'
import { getCourse, type Course } from '../api/course'
import {
  createConversation,
  getCitations,
  listConversations,
  listMessages,
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

const route = useRoute()
const router = useRouter()

const courseId = computed(() => Number(route.params.id))

const course = ref<Course | null>(null)
const courseLoading = ref(false)

const conversations = ref<Conversation[]>([])
const conversationsLoading = ref(false)
const creating = ref(false)
const activeConversationId = ref<number | null>(null)

const messages = ref<ChatMessage[]>([])
const inputText = ref('')
const sending = ref(false)

const messageListRef = ref<HTMLElement | null>(null)

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

  messages.value.push({ role: 'user', content: question })
  inputText.value = ''
  const pendingIndex =
    messages.value.push({
      role: 'agent',
      content: '正在思考...',
      pending: true,
      courseId: courseId.value,
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

function scrollToBottom() {
  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight
  }
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
        <div v-loading="conversationsLoading" class="conversation-list">
          <div
            v-for="conv in conversations"
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
          </div>
          <el-empty
            v-if="!conversationsLoading && conversations.length === 0"
            description="暂无对话"
            :image-size="60"
          />
        </div>
      </div>

      <div class="chat-main">
        <div
          v-if="activeConversationId"
          ref="messageListRef"
          class="message-list"
        >
          <MessageList
            :messages="messages"
            @open-citation="openCitationDrawer"
            @open-retrieval="openRetrievalDrawer"
            @follow-up="handleFollowUp"
          />
        </div>

        <div v-else class="chat-empty">
          <el-empty description="请创建对话">
            <el-button
              type="primary"
              :loading="creating"
              @click="handleCreateConversation"
            >
              创建对话
            </el-button>
          </el-empty>
        </div>

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

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
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
</style>
