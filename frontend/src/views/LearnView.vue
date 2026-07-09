<template>
  <div class="learn-page">
    <!-- Header -->
    <div class="learn-header">
      <el-button link @click="goBack">
        <el-icon><ArrowLeft /></el-icon>
        返回课程
      </el-button>
      <span class="learn-title">{{ courseName || '课程学习' }}</span>
      <el-button
        type="primary"
        plain
        size="small"
        :loading="studyGuideLoading"
        :disabled="chunks.length === 0"
        @click="generateStudyGuide"
      >
        <el-icon><MagicStick /></el-icon>
        生成学习指南
      </el-button>
      <el-select
        v-model="selectedMaterialId"
        placeholder="选择学习资料"
        style="width: 240px"
        @change="loadChunks"
      >
        <el-option
          v-for="m in materials"
          :key="m.id"
          :label="m.filename"
          :value="m.id"
        />
      </el-select>
    </div>

    <!-- Reading progress bar -->
    <el-progress
      v-if="chunks.length > 0"
      :percentage="readProgress"
      :show-text="false"
      :stroke-width="3"
      class="read-progress"
    />

    <!-- Main content: TOC + document reader + AI assistant -->
    <div class="learn-body">
      <!-- Left: Table of Contents -->
      <div v-if="chunks.length > 0" class="doc-toc">
        <div class="toc-label">目录</div>
        <div class="toc-list">
          <div
            v-for="(chunk, idx) in chunks"
            :key="chunk.id"
            class="toc-item"
            :class="{ active: activeChunkIndex === idx }"
            @click="scrollToChunk(idx)"
          >
            <span class="toc-num">{{ idx + 1 }}</span>
            <span class="toc-title">{{ getChunkLabel(chunk) }}</span>
          </div>
        </div>
      </div>

      <!-- Center: Document reader -->
      <div class="doc-reader" @scroll="handleDocScroll">
        <div v-if="docLoading" class="doc-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          加载资料中...
        </div>
        <div v-else-if="chunks.length === 0" class="doc-empty">
          <el-empty description="请选择一份资料开始学习" :image-size="100" />
        </div>
        <div v-else class="doc-content">
          <!-- Filter hint -->
          <div v-if="filteredCount > 0" class="filter-hint">
            <el-tag type="info" size="small" effect="plain">
              已自动过滤 {{ filteredCount }} 个无关片段（封面/目录/页眉等）
            </el-tag>
          </div>

          <!-- AI Study Guide -->
          <div v-if="studyGuide || studyGuideLoading" class="study-guide-card">
            <div class="study-guide-head">
              <el-icon color="#409eff"><MagicStick /></el-icon>
              <span>AI 学习指南</span>
              <el-button text size="small" @click="studyGuide = ''">收起</el-button>
            </div>
            <div v-loading="studyGuideLoading" class="study-guide-body">
              <div v-if="studyGuide" v-html="renderAnswer(studyGuide)"></div>
            </div>
          </div>

          <!-- Document chunks -->
          <div class="doc-chunks" @mouseup="handleSelection">
            <div
              v-for="(chunk, idx) in chunks"
              :key="chunk.id"
              class="doc-chunk"
              :id="`chunk-${chunk.id}`"
            >
              <div class="doc-chunk-head">
                <span class="doc-chunk-num">{{ idx + 1 }}</span>
                <span v-if="chunk.page_no" class="doc-chunk-page">
                  第 {{ chunk.page_no }} 页
                </span>
                <span v-if="chunk.title" class="doc-chunk-title">
                  {{ chunk.title }}
                </span>
              </div>
              <div
                class="doc-chunk-text"
                v-html="highlightTerms(chunk.text)"
              ></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: AI Assistant sidebar -->
      <div class="ai-assistant">
        <div class="ai-assistant-head">
          <el-icon color="#409eff"><ChatDotRound /></el-icon>
          <span>AI 学习助手</span>
        </div>

        <!-- Selected text preview -->
        <div v-if="selectedText" class="selected-text-box">
          <div class="selected-text-label">已选中内容：</div>
          <div class="selected-text-content">{{ selectedText }}</div>
          <el-button
            type="primary"
            size="small"
            class="ask-btn"
            @click="askAboutSelection"
            :loading="aiLoading"
          >
            问AI：这段什么意思？
          </el-button>
        </div>

        <!-- Chat messages -->
        <div class="ai-messages" ref="messagesRef">
          <div v-if="aiMessages.length === 0" class="ai-hint">
            <el-icon color="#909399"><InfoFilled /></el-icon>
            <p>选中上方文档中的任意文字，即可向AI助手提问。</p>
            <p>也可以直接在下方输入框中提问。</p>
          </div>
          <div
            v-for="(msg, i) in aiMessages"
            :key="i"
            :class="['ai-msg', msg.role]"
          >
            <div v-if="msg.role === 'user'" class="ai-msg-bubble user">
              {{ msg.content }}
            </div>
            <div v-else class="ai-msg-bubble assistant">
              <div v-html="renderAnswer(msg.content)"></div>
              <div v-if="msg.citations && msg.citations.length" class="ai-citations">
                <span class="ai-cite-label">引用：</span>
                <span
                  v-for="c in msg.citations"
                  :key="c.chunk_id"
                  class="ai-cite-tag"
                >
                  {{ c.material_name }} · 第{{ c.page_no }}页
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Input -->
        <div class="ai-input-area">
          <el-input
            v-model="inputQuestion"
            type="textarea"
            :rows="2"
            placeholder="输入问题，回车发送"
            @keydown.enter.exact.prevent="askQuestion"
          />
          <el-button
            type="primary"
            @click="askQuestion"
            :loading="aiLoading"
            :disabled="!inputQuestion.trim()"
          >
            发送
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ChatDotRound, InfoFilled, Loading, MagicStick } from '@element-plus/icons-vue'
import { listMaterials, getChunks, type Material, type Chunk } from '../api/material'
import { listCourses, type Course } from '../api/course'
import {
  createConversation,
  sendMessage,
  type ChatResult,
  type Citation,
} from '../api/chat'
import { parseApiError } from '../utils/error'

const route = useRoute()
const router = useRouter()

const courseId = computed(() => Number(route.params.id))
const courseName = ref('')
const materials = ref<Material[]>([])
const selectedMaterialId = ref<number | null>(null)
const rawChunks = ref<Chunk[]>([])
const chunks = ref<Chunk[]>([])
const docLoading = ref(false)
const filteredCount = ref(0)

// AI assistant state
const selectedText = ref('')
const inputQuestion = ref('')
const aiMessages = ref<Array<{
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}>>([])
const aiLoading = ref(false)
const messagesRef = ref<HTMLElement | null>(null)
const conversationId = ref<number | null>(null)

// Study guide state
const studyGuide = ref('')
const studyGuideLoading = ref(false)

// TOC + progress state
const activeChunkIndex = ref(0)
const readProgress = ref(0)

// --- Chunk filtering ---
const USELESS_PATTERNS = [
  /^第[一二三四五六七八九十\d]+章\s*$/,
  /^网络空间安全学院/,
  /^计算机(?:网络|操作系统|数据结构|数据库)\s*$/,
  /^\d{4}年\d*月?\s*$/,
  /^[主讲教师|教师][:：]/,
  /^第\d+章知识导图$/,
]

function isUsefulChunk(chunk: Chunk): boolean {
  const text = chunk.text.trim()
  if (text.length < 40) return false
  for (const pattern of USELESS_PATTERNS) {
    if (pattern.test(text)) return false
  }
  if (chunk.title && chunk.title.trim() === text) return false
  return true
}

function filterUsefulChunks(raw: Chunk[]): Chunk[] {
  const filtered = raw.filter(isUsefulChunk)
  filteredCount.value = raw.length - filtered.length
  return filtered
}

function getChunkLabel(chunk: Chunk): string {
  if (chunk.title && chunk.title.trim()) {
    return chunk.title.length > 20 ? chunk.title.substring(0, 20) + '...' : chunk.title
  }
  if (chunk.page_no) return `第${chunk.page_no}页`
  return '片段'
}

// --- Term highlighting ---
const KEY_TERMS = [
  '数据链路层', '物理层', '网络层', '传输层', '应用层',
  'TCP', 'UDP', 'IP地址', 'IP', 'MAC地址', '路由器', '交换机', '网桥',
  '数据帧', '帧', '分组', '比特', '带宽', '吞吐量', '时延',
  'PPP', 'HDLC', 'CSMA/CD', 'VLAN', 'ARP',
  'OSI', '封装', '解封装', '复用', '分用',
  '局域网', '广域网', '以太网', '信道', '信号',
]

function highlightTerms(text: string): string {
  const escapeHtml = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  let result = escapeHtml(text)
  // Sort by length descending to avoid partial matches
  const sortedTerms = [...KEY_TERMS].sort((a, b) => b.length - a.length)
  for (const term of sortedTerms) {
    const escaped = escapeHtml(term)
    const regex = new RegExp(
      escaped.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
      'g',
    )
    result = result.replace(regex, `<span class="term-highlight">${escaped}</span>`)
  }
  return result
}

// --- Study guide generation ---
async function ensureConversation() {
  if (conversationId.value) return conversationId.value
  const { data } = await createConversation({
    course_id: courseId.value,
    title: '学习助手对话',
  })
  conversationId.value = data.id
  return conversationId.value
}

async function generateStudyGuide() {
  if (chunks.value.length === 0) return
  studyGuideLoading.value = true
  studyGuide.value = ''
  try {
    const convId = await ensureConversation()
    const chunkSummaries = chunks.value
      .slice(0, 20)
      .map((c, i) => `[片段${i + 1}] 第${c.page_no || '?'}页 ${c.title || ''}\n${c.text.substring(0, 200)}`)
      .join('\n\n')
    const question = `请根据以下课程资料片段，生成一份结构化的学习指南，包含：
1. 本章节核心概念（3-5个关键词）
2. 重点知识点梳理（按逻辑顺序组织）
3. 常见易错点或难点提示

资料片段：
${chunkSummaries}`

    const { data } = await sendMessage({
      course_id: courseId.value,
      conversation_id: convId,
      question,
    })
    studyGuide.value = (data as ChatResult).answer
  } catch (err) {
    ElMessage.error(parseApiError(err, '学习指南生成失败'))
  } finally {
    studyGuideLoading.value = false
  }
}

// --- Scroll + progress ---
function scrollToChunk(idx: number) {
  const el = document.getElementById(`chunk-${chunks.value[idx].id}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function handleDocScroll() {
  const reader = document.querySelector('.doc-reader') as HTMLElement
  if (!reader) return
  const scrollTop = reader.scrollTop
  const scrollHeight = reader.scrollHeight - reader.clientHeight
  readProgress.value = scrollHeight > 0 ? Math.round((scrollTop / scrollHeight) * 100) : 0

  for (let i = chunks.value.length - 1; i >= 0; i--) {
    const el = document.getElementById(`chunk-${chunks.value[i].id}`)
    if (el && el.offsetTop - reader.offsetTop <= scrollTop + 60) {
      activeChunkIndex.value = i
      break
    }
  }
}

// --- Lifecycle ---
onMounted(async () => {
  try {
    const { data: courseData } = await listCourses({ page: 1, page_size: 100 })
    const course = courseData.items.find((c: Course) => c.id === courseId.value)
    if (course) courseName.value = course.name
  } catch {
    // ignore
  }

  try {
    const { data } = await listMaterials(courseId.value)
    materials.value = data.items.filter((m: Material) => m.status === 'ready')
    if (materials.value.length > 0) {
      const queryMaterialId = route.query.material_id
        ? Number(route.query.material_id)
        : null
      const match = queryMaterialId
        ? materials.value.find((m) => m.id === queryMaterialId)
        : null
      selectedMaterialId.value = match ? match.id : materials.value[0].id
      await loadChunks()

      const queryChunkId = route.query.chunk_id
      if (queryChunkId) {
        await nextTick()
        const el = document.getElementById(`chunk-${queryChunkId}`)
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }

      const queryAsk = route.query.ask
      if (queryAsk && typeof queryAsk === 'string') {
        inputQuestion.value = `请解释这段内容：\n"${queryAsk}"`
        await askQuestion()
      }
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取资料列表失败'))
  }
})

async function loadChunks() {
  if (!selectedMaterialId.value) return
  docLoading.value = true
  chunks.value = []
  studyGuide.value = ''
  try {
    const { data } = await getChunks(selectedMaterialId.value, { page: 1, page_size: 100 })
    rawChunks.value = data.items
    chunks.value = filterUsefulChunks(data.items)
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取资料内容失败'))
  } finally {
    docLoading.value = false
  }
}

function handleSelection() {
  const selection = window.getSelection()
  if (selection && selection.toString().trim().length > 5) {
    selectedText.value = selection.toString().trim().substring(0, 500)
  }
}

function askAboutSelection() {
  if (!selectedText.value) return
  inputQuestion.value = `请解释这段内容：\n"${selectedText.value}"`
  askQuestion()
}

async function askQuestion() {
  const question = inputQuestion.value.trim()
  if (!question || aiLoading.value) return

  aiMessages.value.push({ role: 'user', content: question })
  inputQuestion.value = ''
  selectedText.value = ''
  aiLoading.value = true

  await nextTick()
  scrollToBottom()

  try {
    const convId = await ensureConversation()
    const { data } = await sendMessage({
      course_id: courseId.value,
      conversation_id: convId,
      question,
    })
    const result = data as ChatResult
    aiMessages.value.push({
      role: 'assistant',
      content: result.answer,
      citations: result.citations,
    })
  } catch (err) {
    aiMessages.value.push({
      role: 'assistant',
      content: `抱歉，回答生成失败：${parseApiError(err, '请稍后重试')}`,
    })
  } finally {
    aiLoading.value = false
    await nextTick()
    scrollToBottom()
  }
}

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

function renderAnswer(text: string): string {
  return text.replace(/\n/g, '<br>')
}

function goBack() {
  router.push(`/courses/${courseId.value}`)
}
</script>

<style scoped>
.learn-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.learn-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 20px;
  border-bottom: 1px solid #ebeef5;
  background: #fff;
}

.learn-title {
  font-size: 16px;
  font-weight: 600;
  flex: 1;
}

.read-progress {
  flex-shrink: 0;
}

.read-progress :deep(.el-progress-bar__outer) {
  border-radius: 0;
}

.learn-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* Table of Contents */
.doc-toc {
  width: 200px;
  flex-shrink: 0;
  border-right: 1px solid #ebeef5;
  background: #fff;
  overflow-y: auto;
  padding: 12px 0;
}

.toc-label {
  font-size: 12px;
  font-weight: 600;
  color: #909399;
  padding: 0 16px 8px;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.toc-list {
  display: flex;
  flex-direction: column;
}

.toc-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  cursor: pointer;
  transition: all 0.2s;
  border-left: 3px solid transparent;
}

.toc-item:hover {
  background: #f5f7fa;
}

.toc-item.active {
  background: #ecf5ff;
  border-left-color: #409eff;
}

.toc-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  background: #f0f0f0;
  color: #909399;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.toc-item.active .toc-num {
  background: #409eff;
  color: #fff;
}

.toc-title {
  font-size: 13px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toc-item.active .toc-title {
  color: #409eff;
  font-weight: 600;
}

/* Document reader */
.doc-reader {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  background: #fafafa;
}

.doc-loading,
.doc-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
  gap: 8px;
}

.doc-content {
  max-width: 800px;
  margin: 0 auto;
}

.filter-hint {
  margin-bottom: 16px;
}

/* Study guide card */
.study-guide-card {
  margin-bottom: 24px;
  background: linear-gradient(135deg, #ecf5ff 0%, #f0f9eb 100%);
  border: 1px solid #d9ecff;
  border-radius: 10px;
  overflow: hidden;
}

.study-guide-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid #d9ecff;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.study-guide-head .el-button {
  margin-left: auto;
}

.study-guide-body {
  padding: 16px;
  font-size: 14px;
  line-height: 1.8;
  color: #303133;
  min-height: 80px;
}

/* Document chunks */
.doc-chunks {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.doc-chunk {
  padding: 16px 20px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  border-left: 4px solid #409eff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  transition: box-shadow 0.2s;
}

.doc-chunk:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.doc-chunk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f0f0f0;
}

.doc-chunk-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.doc-chunk-page {
  font-size: 12px;
  color: #909399;
}

.doc-chunk-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.doc-chunk-text {
  font-size: 14px;
  line-height: 1.8;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Term highlight */
:deep(.term-highlight) {
  background: #fff3a0;
  color: #303133;
  padding: 0 2px;
  border-radius: 2px;
  font-weight: 600;
}

/* AI Assistant */
.ai-assistant {
  width: 380px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #ebeef5;
  background: #fff;
}

.ai-assistant-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.selected-text-box {
  margin: 12px;
  padding: 12px;
  background: #ecf5ff;
  border-radius: 8px;
  border: 1px solid #d9ecff;
}

.selected-text-label {
  font-size: 12px;
  color: #409eff;
  font-weight: 600;
  margin-bottom: 4px;
}

.selected-text-content {
  font-size: 13px;
  color: #303133;
  line-height: 1.5;
  max-height: 100px;
  overflow-y: auto;
  margin-bottom: 8px;
  white-space: pre-wrap;
}

.ask-btn {
  width: 100%;
}

.ai-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.ai-hint {
  text-align: center;
  color: #909399;
  padding: 40px 16px;
}

.ai-hint p {
  margin: 8px 0;
  font-size: 13px;
}

.ai-msg {
  margin-bottom: 16px;
}

.ai-msg-bubble {
  border-radius: 12px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.6;
}

.ai-msg-bubble.user {
  background: #409eff;
  color: #fff;
  margin-left: 40px;
  text-align: right;
}

.ai-msg-bubble.assistant {
  background: #f4f4f5;
  color: #303133;
  margin-right: 40px;
}

.ai-citations {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #e4e7ed;
}

.ai-cite-label {
  font-size: 12px;
  color: #909399;
}

.ai-cite-tag {
  display: inline-block;
  font-size: 12px;
  color: #409eff;
  background: #ecf5ff;
  padding: 2px 6px;
  border-radius: 4px;
  margin-right: 4px;
  margin-bottom: 4px;
}

.ai-input-area {
  padding: 12px 16px;
  border-top: 1px solid #ebeef5;
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.ai-input-area .el-button {
  flex-shrink: 0;
}
</style>
