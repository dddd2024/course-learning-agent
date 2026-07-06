<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  ChatDotRound,
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
  type ChatResult,
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

const expandedCitationKeys = ref<Set<string>>(new Set())

const drawerVisible = ref(false)
const drawerCitation = ref<Citation | null>(null)
const drawerMessage = ref<ChatMessage | null>(null)
const drawerLoading = ref(false)

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

function citationKey(messageId: number | undefined, chunkId: number): string {
  return `${messageId ?? 'tmp'}-${chunkId}`
}

function isCitationExpanded(
  messageId: number | undefined,
  chunkId: number,
): boolean {
  return expandedCitationKeys.value.has(citationKey(messageId, chunkId))
}

function toggleCitationExpand(
  messageId: number | undefined,
  chunkId: number,
): void {
  const key = citationKey(messageId, chunkId)
  if (expandedCitationKeys.value.has(key)) {
    expandedCitationKeys.value.delete(key)
  } else {
    expandedCitationKeys.value.add(key)
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
  await nextTick()
  scrollToBottom()

  try {
    const { data } = await sendMessage({
      course_id: courseId.value,
      conversation_id: activeConversationId.value,
      question,
    })
    applyChatResult(pendingIndex, data)
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
                    class="citation-cards"
                  >
                    <div
                      v-for="cit in msg.citations"
                      :key="cit.chunk_id"
                      class="citation-card"
                      @click="openCitationDrawer(cit, msg)"
                    >
                      <div class="citation-head">
                        <span class="citation-material">
                          {{ cit.material_name }}
                        </span>
                        <el-tag size="small" type="info">
                          第 {{ cit.page_no }} 页
                        </el-tag>
                      </div>
                      <div class="citation-quote">
                        <template
                          v-if="isCitationExpanded(msg.messageId, cit.chunk_id)"
                        >
                          {{ cit.quote_text }}
                        </template>
                        <template v-else>
                          {{ truncate(cit.quote_text) }}
                        </template>
                      </div>
                      <div class="citation-foot">
                        <span class="citation-confidence">
                          相关度 {{ confidencePercent(cit.confidence) }}%
                        </span>
                        <el-progress
                          :percentage="confidencePercent(cit.confidence)"
                          :stroke-width="6"
                          :show-text="false"
                          class="citation-progress"
                        />
                        <el-button
                          text
                          size="small"
                          @click.stop="
                            toggleCitationExpand(msg.messageId, cit.chunk_id)
                          "
                        >
                          {{
                            isCitationExpanded(msg.messageId, cit.chunk_id)
                              ? '收起'
                              : '展开'
                          }}
                        </el-button>
                        <el-button
                          text
                          size="small"
                          @click.stop="openCitationDrawer(cit, msg)"
                        >
                          详情
                        </el-button>
                      </div>
                    </div>
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

.citation-cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.citation-card {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.citation-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.1);
}

.citation-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.citation-material {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.citation-quote {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
  margin-bottom: 8px;
  white-space: pre-wrap;
  word-break: break-word;
}

.citation-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.citation-confidence {
  font-size: 12px;
  color: #67c23a;
  flex-shrink: 0;
}

.citation-progress {
  flex: 1;
  min-width: 60px;
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
