<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  ChatDotRound,
  CircleCheck,
  CircleClose,
  Document,
  Loading,
  Plus,
  Promotion,
  User,
} from '@element-plus/icons-vue'
import { getCourse, type Course } from '../api/course'
import {
  createConversation,
  getCitations,
  listConversations,
  sendMessage,
  sendMessageStream,
  type ChatResult,
  type ChatStreamEvent,
  type Citation,
  type Conversation,
  type RetrievedChunk,
  type ReliabilityLevel,
} from '../api/chat'
import { parseApiError } from '../utils/error'

interface ChatMessage {
  role: 'user' | 'agent'
  content: string
  messageId?: number
  citations?: Citation[]
  notFound?: boolean
  followUpQuestions?: string[]
  reliabilityLevel?: ReliabilityLevel
  retrievedChunks?: RetrievedChunk[]
  pending?: boolean
}

// Phase 2 Task B: a single step in the SSE progress timeline.
interface StreamStep {
  step: string
  status: 'running' | 'done' | 'error'
  message: string
  advice?: string
}

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

// Phase 2 Task B: SSE status-panel state.
// - streamSteps: ordered list of steps for the in-flight request.
// - streamError: when set, the panel expands to show advice.
// - statusExpanded: manual collapse control (auto-expands on send/error).
const streamSteps = ref<StreamStep[]>([])
const streamError = ref<string | null>(null)
const streamAdvice = ref<string | null>(null)
const statusExpanded = ref(false)

function confidencePercent(confidence: number): number {
  if (confidence > 1) return Math.min(100, Math.round(confidence))
  return Math.min(100, Math.round(confidence * 100))
}

function truncate(text: string, max = 120): string {
  if (!text) return ''
  return text.length > max ? text.slice(0, max) + '…' : text
}

function reliabilityTagType(
  level: ReliabilityLevel,
): 'success' | 'warning' | 'danger' {
  switch (level) {
    case 'high':
      return 'success'
    case 'medium':
      return 'warning'
    case 'low':
      return 'warning'
    case 'failed':
      return 'danger'
  }
}

function reliabilityLabel(level: ReliabilityLevel): string {
  switch (level) {
    case 'high':
      return '高'
    case 'medium':
      return '中'
    case 'low':
      return '低'
    case 'failed':
      return '失败'
  }
}

function reliabilityHint(level: ReliabilityLevel): string {
  switch (level) {
    case 'high':
      return '回答有充分资料依据'
    case 'medium':
      return '回答有部分资料依据，建议核实'
    case 'low':
      return '回答缺少资料依据，请谨慎参考'
    case 'failed':
      return '未找到可靠资料依据'
  }
}

function chunkScorePercent(score: number): number {
  if (score > 1) return Math.min(100, Math.round(score))
  return Math.min(100, Math.round(score * 100))
}

// Phase 2 Task A: build the capsule label. Prefer the backend-assembled
// ``display_label``; fall back to client-side assembly for older data.
function capsuleLabel(cit: Citation): string {
  if (cit.display_label) return cit.display_label
  if (cit.page_no !== null && cit.page_no !== undefined) {
    return `${cit.material_name} · 第 ${cit.page_no} 页`
  }
  return cit.material_name || `片段 ${cit.chunk_id}`
}

// Phase 2 Task B: human-readable label for an SSE step name.
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

async function selectConversation(conv: Conversation) {
  if (activeConversationId.value === conv.id) return
  activeConversationId.value = conv.id
  messages.value = []
  resetStreamState()
  statusExpanded.value = false
  await nextTick()
  scrollToBottom()
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
    // POST /chat endpoint if the stream connection itself fails.
    let result: ChatResult | null = null
    try {
      result = await sendMessageStream(payload, handleStreamEvent)
    } catch (streamErr) {
      // Network / fetch error before any event arrived → fallback.
      const { data } = await sendMessage(payload)
      result = data
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
  drawerVisible.value = true
  if (msg.messageId) {
    drawerLoading.value = true
    try {
      const { data } = await getCitations(msg.messageId)
      const full = data.items.find((c) => c.chunk_id === citation.chunk_id)
      if (full) {
        drawerCitation.value = full
      }
    } catch {
      // 静默失败，使用内联数据
    } finally {
      drawerLoading.value = false
    }
  }
}

function openRetrievalDrawer(msg: ChatMessage) {
  drawerCitation.value = null
  drawerMessage.value = msg
  drawerVisible.value = true
}

const drawerTitle = computed(() => {
  if (drawerCitation.value) return '引用详情'
  return '检索过程'
})

// Phase 2 Task B: the current running step (if any) for the header chip.
const currentRunningStep = computed(() =>
  streamSteps.value.find((s) => s.status === 'running'),
)

const hasStreamError = computed(() => streamError.value !== null)

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
          <el-empty
            v-if="messages.length === 0"
            description="开始提问吧，Agent 将基于课程资料回答"
            :image-size="80"
          />
          <template v-for="(msg, idx) in messages" :key="idx">
            <div
              class="message-row"
              :class="msg.role === 'user' ? 'message-user' : 'message-agent'"
            >
              <div class="message-avatar">
                <el-icon v-if="msg.role === 'user'"><User /></el-icon>
                <el-icon v-else><ChatDotRound /></el-icon>
              </div>
              <div class="message-bubble-wrap">
                <div class="message-bubble">
                  <template v-if="msg.pending">
                    <el-icon class="is-loading"><Loading /></el-icon>
                    <span class="pending-text">{{ msg.content }}</span>
                  </template>
                  <template v-else>{{ msg.content }}</template>
                </div>

                <div
                  v-if="msg.role === 'agent' && !msg.pending && msg.reliabilityLevel"
                  class="reliability-area"
                >
                  <el-alert
                    v-if="msg.reliabilityLevel === 'failed'"
                    title="未找到可靠资料依据"
                    type="error"
                    :closable="false"
                    show-icon
                    class="reliability-alert"
                  />
                  <div v-else class="reliability-tag-row">
                    <el-tag
                      :type="reliabilityTagType(msg.reliabilityLevel)"
                      effect="dark"
                      size="small"
                    >
                      可靠性：{{ reliabilityLabel(msg.reliabilityLevel) }}
                    </el-tag>
                    <span class="reliability-hint">
                      {{ reliabilityHint(msg.reliabilityLevel) }}
                    </span>
                  </div>
                </div>

                <div
                  v-if="msg.role === 'agent' && !msg.pending"
                  class="citations-area"
                >
                  <div class="citations-title">
                    <el-icon><Document /></el-icon>
                    <span>引用资料 ({{ msg.citations?.length ?? 0 }})</span>
                    <el-button
                      v-if="msg.retrievedChunks && msg.retrievedChunks.length > 0"
                      text
                      size="small"
                      class="retrieval-btn"
                      @click="openRetrievalDrawer(msg)"
                    >
                      检索过程 ({{ msg.retrievedChunks.length }})
                    </el-button>
                  </div>

                  <div
                    v-if="msg.citations && msg.citations.length > 0"
                    class="citation-capsules"
                  >
                    <span
                      v-for="(cit, ci) in msg.citations"
                      :key="cit.chunk_id"
                      class="citation-capsule"
                      :title="`相关度 ${confidencePercent(cit.confidence)}%`"
                      @click="openCitationDrawer(cit, msg)"
                    >
                      <span class="capsule-index">{{ ci + 1 }}</span>
                      <span class="capsule-label">{{ capsuleLabel(cit) }}</span>
                    </span>
                  </div>
                  <div v-else class="no-citation">
                    本次回答未找到直接资料依据
                  </div>

                  <div
                    v-if="
                      msg.followUpQuestions && msg.followUpQuestions.length > 0
                    "
                    class="follow-ups"
                  >
                    <div class="follow-ups-title">追问建议：</div>
                    <div class="follow-up-chips">
                      <el-tag
                        v-for="(q, qi) in msg.followUpQuestions"
                        :key="qi"
                        class="follow-up-chip"
                        effect="plain"
                        @click="handleFollowUp(q)"
                      >
                        {{ q }}
                      </el-tag>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
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

        <div
          v-if="activeConversationId && streamSteps.length > 0"
          class="stream-status"
          :class="{
            'status-error': hasStreamError,
            'status-collapsed': !statusExpanded,
          }"
        >
          <div class="status-header" @click="toggleStatusPanel">
            <el-icon
              v-if="currentRunningStep && !hasStreamError"
              class="is-loading"
            >
              <Loading />
            </el-icon>
            <el-icon v-else-if="hasStreamError" class="status-err-icon">
              <CircleClose />
            </el-icon>
            <el-icon v-else class="status-ok-icon">
              <CircleCheck />
            </el-icon>
            <span class="status-summary">
              <template v-if="hasStreamError">
                处理失败：{{ streamError }}
              </template>
              <template v-else-if="currentRunningStep">
                {{ currentRunningStep.message }}
              </template>
              <template v-else>
                已完成（{{ streamSteps.length }} 个步骤）
              </template>
            </span>
            <el-icon class="status-toggle">
              <ArrowUp v-if="statusExpanded" />
              <ArrowDown v-else />
            </el-icon>
          </div>
          <div v-if="statusExpanded" class="status-body">
            <div
              v-for="s in streamSteps"
              :key="s.step"
              class="status-step"
              :class="`step-${s.status}`"
            >
              <el-icon v-if="s.status === 'running'" class="is-loading">
                <Loading />
              </el-icon>
              <el-icon v-else-if="s.status === 'done'" class="step-done-icon">
                <CircleCheck />
              </el-icon>
              <el-icon v-else class="step-err-icon">
                <CircleClose />
              </el-icon>
              <span class="step-name">{{ stepLabel(s.step) }}</span>
              <span class="step-message">{{ s.message }}</span>
            </div>
            <el-alert
              v-if="hasStreamError && streamAdvice"
              :title="streamAdvice"
              type="warning"
              :closable="false"
              show-icon
              class="status-advice"
            />
          </div>
        </div>

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

    <el-drawer
      v-model="drawerVisible"
      :title="drawerTitle"
      direction="rtl"
      size="480px"
    >
      <div v-loading="drawerLoading" class="drawer-body">
        <template v-if="drawerCitation">
          <div class="drawer-section">
            <div class="drawer-label">资料名称</div>
            <div class="drawer-value">{{ drawerCitation.material_name }}</div>
          </div>
          <div class="drawer-section">
            <div class="drawer-label">页码</div>
            <div class="drawer-value">第 {{ drawerCitation.page_no }} 页</div>
          </div>
          <div class="drawer-section">
            <div class="drawer-label">相关度</div>
            <div class="drawer-value">
              <span class="confidence-text">
                相关度 {{ confidencePercent(drawerCitation.confidence) }}%
              </span>
              <el-progress
                :percentage="confidencePercent(drawerCitation.confidence)"
                :stroke-width="8"
              />
            </div>
          </div>
          <div class="drawer-section">
            <div class="drawer-label">片段内容</div>
            <div class="drawer-quote">{{ drawerCitation.quote_text }}</div>
          </div>
        </template>

        <div
          v-if="
            drawerMessage?.followUpQuestions &&
            drawerMessage.followUpQuestions.length > 0
          "
          class="drawer-section"
        >
          <div class="drawer-label">追问建议</div>
          <div class="follow-up-chips">
            <el-tag
              v-for="(q, qi) in drawerMessage.followUpQuestions"
              :key="qi"
              class="follow-up-chip"
              effect="plain"
              @click="handleFollowUp(q)"
            >
              {{ q }}
            </el-tag>
          </div>
        </div>

        <div class="drawer-section">
          <div class="drawer-label">
            检索命中 ({{ drawerMessage?.retrievedChunks?.length ?? 0 }})
          </div>
          <template
            v-if="
              drawerMessage?.retrievedChunks &&
              drawerMessage.retrievedChunks.length > 0
            "
          >
            <div class="retrieval-list">
              <div
                v-for="chunk in drawerMessage.retrievedChunks"
                :key="chunk.chunk_id"
                class="retrieval-item"
                :class="{ 'retrieval-cited': chunk.is_cited }"
              >
                <div class="retrieval-head">
                  <span class="retrieval-title">
                    {{ chunk.title || `片段 ${chunk.chunk_id}` }}
                  </span>
                  <el-tag
                    v-if="chunk.is_cited"
                    type="success"
                    size="small"
                    effect="plain"
                  >
                    已引用
                  </el-tag>
                  <el-tag v-else type="info" size="small" effect="plain">
                    未引用
                  </el-tag>
                </div>
                <div class="retrieval-meta">
                  <el-tag
                    v-if="chunk.page_no !== null && chunk.page_no !== undefined"
                    type="info"
                    size="small"
                    effect="plain"
                  >
                    第 {{ chunk.page_no }} 页
                  </el-tag>
                  <span class="retrieval-score">评分 {{ chunk.score }}</span>
                  <el-progress
                    :percentage="chunkScorePercent(chunk.score)"
                    :stroke-width="6"
                    :show-text="false"
                    class="retrieval-progress"
                  />
                </div>
                <div class="retrieval-snippet">
                  {{ truncate(chunk.snippet, 80) }}
                </div>
              </div>
            </div>
          </template>
          <el-empty
            v-else
            description="未找到可靠资料依据"
            :image-size="60"
          />
        </div>
      </div>
    </el-drawer>
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

.message-row {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.message-user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 16px;
}

.message-user .message-avatar {
  background: #409eff;
  color: #fff;
}

.message-agent .message-avatar {
  background: #67c23a;
  color: #fff;
}

.message-bubble-wrap {
  max-width: 75%;
  display: flex;
  flex-direction: column;
}

.message-user .message-bubble-wrap {
  align-items: flex-end;
}

.message-agent .message-bubble-wrap {
  align-items: flex-start;
}

.message-bubble {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-bubble .is-loading {
  margin-right: 6px;
  vertical-align: middle;
}

.pending-text {
  vertical-align: middle;
}

.message-user .message-bubble {
  background: #409eff;
  color: #fff;
  border-top-right-radius: 2px;
}

.message-agent .message-bubble {
  background: #f5f7fa;
  color: #303133;
  border-top-left-radius: 2px;
}

.not-found-alert {
  margin-top: 8px;
  width: 100%;
}

.reliability-area {
  margin-top: 8px;
  width: 100%;
}

.reliability-alert {
  width: 100%;
}

.reliability-tag-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.reliability-hint {
  font-size: 12px;
  color: #909399;
}

.retrieval-btn {
  margin-left: auto;
  padding: 0;
}

.citations-area {
  margin-top: 10px;
  width: 100%;
}

.citations-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.citation-capsules {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.citation-capsule {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 999px;
  background: #f4f6f9;
  border: 1px solid #e4e7ed;
  font-size: 12px;
  color: #606266;
  cursor: pointer;
  transition: all 0.2s;
  max-width: 280px;
}

.citation-capsule:hover {
  background: #ecf5ff;
  border-color: #c6e2ff;
  color: #409eff;
}

.capsule-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #dcdfe6;
  color: #606266;
  font-size: 10px;
  font-weight: 600;
  flex-shrink: 0;
}

.citation-capsule:hover .capsule-index {
  background: #409eff;
  color: #fff;
}

.capsule-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.no-citation {
  font-size: 12px;
  color: #909399;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 4px;
}

.follow-ups {
  margin-top: 10px;
}

.follow-ups-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.follow-up-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.follow-up-chip {
  cursor: pointer;
  transition: all 0.2s;
}

.follow-up-chip:hover {
  color: #409eff;
  border-color: #409eff;
  cursor: pointer;
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

/* Phase 2 Task B: SSE real-time status panel */
.stream-status {
  border-top: 1px solid #ebeef5;
  background: #fafbfc;
  flex-shrink: 0;
}

.stream-status.status-error {
  background: #fef0f0;
  border-top-color: #fbc4c4;
}

.status-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  color: #606266;
}

.status-header:hover {
  background: #f5f7fa;
}

.stream-status.status-error .status-header {
  color: #f56c6c;
}

.status-summary {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-err-icon {
  color: #f56c6c;
  flex-shrink: 0;
}

.status-ok-icon {
  color: #67c23a;
  flex-shrink: 0;
}

.status-toggle {
  color: #909399;
  flex-shrink: 0;
}

.status-body {
  padding: 4px 16px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.status-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 4px 0;
}

.step-name {
  font-weight: 600;
  color: #303133;
  flex-shrink: 0;
  min-width: 64px;
}

.step-message {
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.status-step.step-running .step-name {
  color: #409eff;
}

.status-step.step-done .step-name {
  color: #67c23a;
}

.step-done-icon {
  color: #67c23a;
  flex-shrink: 0;
}

.step-err-icon {
  color: #f56c6c;
  flex-shrink: 0;
}

.status-advice {
  margin-top: 4px;
}

.chat-input :deep(.el-textarea) {
  flex: 1;
}

.drawer-body {
  padding: 0 20px 20px;
}

.drawer-section {
  margin-bottom: 20px;
}

.drawer-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.drawer-value {
  font-size: 14px;
  color: #303133;
}

.confidence-text {
  display: inline-block;
  margin-bottom: 6px;
  font-size: 14px;
  color: #67c23a;
}

.drawer-quote {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  white-space: pre-wrap;
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  max-height: 240px;
  overflow-y: auto;
  word-break: break-word;
}

.retrieval-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.retrieval-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
  background: #fafafa;
}

.retrieval-cited {
  border-color: #b3e19d;
  background: #f0f9eb;
}

.retrieval-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.retrieval-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.retrieval-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.retrieval-score {
  font-size: 12px;
  color: #606266;
  flex-shrink: 0;
}

.retrieval-progress {
  flex: 1;
  min-width: 60px;
}

.retrieval-snippet {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
