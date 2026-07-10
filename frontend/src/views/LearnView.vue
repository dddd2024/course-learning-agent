<template>
  <div class="learn-page">
    <!-- Header -->
    <div class="learn-header">
      <el-button link @click="goBack">
        <el-icon><ArrowLeft /></el-icon>
        返回课程
      </el-button>
      <h2 class="learn-title">{{ courseName || '课程学习' }}</h2>
      <el-button
        type="primary"
        plain
        size="small"
        :loading="studyGuideLoading"
        :disabled="chunks.length === 0"
        @click="generateStudyGuide"
      >
        <el-icon><MagicStick /></el-icon>
        生成内容速览
      </el-button>
      <el-select
        v-model="selectedMaterialId"
        placeholder="选择学习资料"
        class="material-select"
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

    <div v-if="chunks.length > 0" class="mobile-pane-switch" role="tablist" aria-label="学习视图">
      <button
        type="button"
        role="tab"
        :aria-selected="mobilePane === 'toc'"
        :class="{ active: mobilePane === 'toc' }"
        @click="mobilePane = 'toc'"
      >
        目录
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="mobilePane === 'content'"
        :class="{ active: mobilePane === 'content' }"
        @click="mobilePane = 'content'"
      >
        正文
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="mobilePane === 'assistant'"
        :class="{ active: mobilePane === 'assistant' }"
        @click="mobilePane = 'assistant'"
      >
        AI 助手
      </button>
    </div>

    <!-- Main content: TOC + document reader + AI assistant -->
    <div class="learn-body">
      <!-- Left: Table of Contents -->
      <div v-if="chunks.length > 0" class="doc-toc" :class="{ 'mobile-hidden': mobilePane !== 'toc' }">
        <div class="toc-label">目录</div>
        <div class="toc-list">
          <div
            v-for="(chunk, idx) in chunks"
            :key="chunk.id"
            class="toc-item"
            :class="{ active: activeChunkIndex === idx }"
            role="button"
            tabindex="0"
            @click="scrollToChunk(idx)"
            @keydown.enter="scrollToChunk(idx)"
            @keydown.space.prevent="scrollToChunk(idx)"
          >
            <span class="toc-num">{{ idx + 1 }}</span>
            <span class="toc-title">{{ getChunkLabel(chunk) }}</span>
          </div>
        </div>
      </div>

      <!-- Center: Document reader -->
      <div class="doc-reader" :class="{ 'mobile-hidden': mobilePane !== 'content' }" @scroll="handleDocScroll">
        <div v-if="docLoading" class="doc-loading" role="status" aria-live="polite">
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
              <span>AI 内容速览</span>
              <el-tag size="small" type="info" effect="plain">基于前 20 个片段</el-tag>
              <el-button
                v-if="studyGuide"
                text
                size="small"
                @click="copyMessage(studyGuide)"
              >
                <el-icon><CopyDocument /></el-icon> 复制
              </el-button>
              <el-button text size="small" @click="studyGuide = ''">收起</el-button>
            </div>
            <div v-loading="studyGuideLoading" class="study-guide-body">
              <div v-if="studyGuide" class="markdown-content" v-html="renderAnswer(studyGuide)"></div>
            </div>
          </div>

          <!-- Knowledge point focus banner -->
          <div v-if="kpTitle" class="kp-focus-banner">
            <div class="kp-focus-head">
              <el-icon color="#409eff"><Aim /></el-icon>
              <span class="kp-focus-title">当前学习知识点：{{ kpTitle }}</span>
              <el-button
                type="primary"
                plain
                size="small"
                :loading="aiLoading"
                @click="askAboutKnowledgePoint"
              >
                让 AI 讲解
              </el-button>
              <el-button text size="small" @click="kpTitle = ''; kpSummary = ''; kpFilterActive = false; loadChunks()">关闭</el-button>
            </div>
            <div v-if="kpSummary" class="kp-focus-summary">{{ kpSummary }}</div>
            <div v-if="kpFilterActive" class="kp-filter-note">
              已筛选显示该知识点相关的 {{ chunks.length }} 个内容片段（共 {{ rawChunks.length }} 个）
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
              <div v-if="chunk.images && chunk.images.length > 0" class="doc-chunk-images">
                <div
                  v-for="img in chunk.images"
                  :key="img.id"
                  class="doc-chunk-image-item"
                >
                  <el-image
                    :src="`${UPLOAD_BASE_URL}/${img.image_path}`"
                    :preview-src-list="[`${UPLOAD_BASE_URL}/${img.image_path}`]"
                    :alt="`${materials.find((m) => m.id === selectedMaterialId)?.filename || '课程资料'}第 ${chunk.page_no || '?'} 页插图`"
                    fit="contain"
                    style="max-width: 100%; max-height: 400px; border-radius: 6px;"
                    loading="lazy"
                  >
                    <template #placeholder>
                      <div class="image-placeholder">图片加载中...</div>
                    </template>
                    <template #error>
                      <div class="image-error">图片加载失败</div>
                    </template>
                  </el-image>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: AI Assistant sidebar -->
      <div class="ai-assistant" :class="{ 'mobile-hidden': mobilePane !== 'assistant' }">
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
        <div class="ai-messages" ref="messagesRef" aria-live="polite" aria-relevant="additions">
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
              <div class="markdown-content" v-html="renderAnswer(msg.content)"></div>
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
              <div class="ai-msg-actions">
                <el-button text size="small" @click="copyMessage(msg.content)">
                  <el-icon><CopyDocument /></el-icon> 复制
                </el-button>
              </div>
            </div>
          </div>
        </div>

        <!-- Input -->
        <div class="ai-input-area">
          <div class="ai-toolbar">
            <el-button text size="small" @click="clearAiConversation" :disabled="aiMessages.length === 0">
              清空对话
            </el-button>
            <el-button v-if="aiLoading" text size="small" type="danger" @click="stopAiGeneration">
              停止生成
            </el-button>
          </div>
          <div class="ai-input-row">
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
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ChatDotRound, CopyDocument, InfoFilled, Loading, MagicStick, Aim } from '@element-plus/icons-vue'
import { listMaterials, getChunks, type Material, type Chunk } from '../api/material'
import { listCourses, type Course } from '../api/course'
import {
  createConversation,
  sendMessage,
  type ChatResult,
  type Citation,
} from '../api/chat'
import { listKnowledgePoints } from '../api/knowledge'
import { parseApiError } from '../utils/error'
import { renderMarkdown } from '../utils/markdown'
import { UPLOAD_BASE_URL } from '../config/api'

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
const mobilePane = ref<'toc' | 'content' | 'assistant'>('content')

// AI assistant state
const selectedText = ref('')
const inputQuestion = ref('')
const aiMessages = ref<Array<{
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}>>([])
const aiLoading = ref(false)
const abortController = ref<AbortController | null>(null)
const messagesRef = ref<HTMLElement | null>(null)
const conversationId = ref<number | null>(null)

// Study guide state
const studyGuide = ref('')
const studyGuideLoading = ref(false)

// Knowledge point focus (from outline navigation)
const kpTitle = ref('')
const kpSummary = ref('')
const kpSourceChunkIds = ref<Set<number>>(new Set())
const kpFilterActive = ref(false)

// TOC + progress state
const activeChunkIndex = ref(0)
const readProgress = ref(0)

// --- Chunk filtering ---
// NOTE: patterns below are intentionally GENERIC (chapter headers, page
// numbers, dates, teacher info, section headers). Course-specific noise
// (author tags like [Forouzan]/[Tanenbaum], school names, etc.) must NOT
// live here — add such handling per-course if ever needed again.
const USELESS_PATTERNS = [
  // Chapter headers (e.g. "第一章", "第3章")
  /^第[一二三四五六七八九十\d]+章\s*$/,
  // Year-only lines on cover/header pages
  /^\d{4}年\d*月?\s*$/,
  // Teacher info
  /^[主讲教师|教师][:：]/,
  // Knowledge map headers
  /^第\d+章知识导图$/,
  // Date + semester info on cover pages
  /^\d{4}年(?:春|秋|夏|冬)\s*$/,
  // "本章学习" / "本章小结" / "学习目标" section headers without content
  /^(?:本章学习|本章小结|学习目标|教学目标)\s*$/,
  // Pure page numbers
  /^第?\d+页\s*$/,
]

// Lines that, if present, make the whole chunk likely a cover/header
const NOISE_LINE_PATTERNS = [
  /^\d{4}年(?:春|秋|夏|冬)/,           // "2026年春"
  /^\d{4}年\d+月/,                       // "2026年5月"
  /^第\d+页/,
  /^[主讲教师|教师][:：]/,
]

// Inline noise patterns: removed from within lines (not just whole lines)
// e.g. "42026年春" → "4"
const INLINE_NOISE_PATTERNS = [
  /\d{4}年(?:\d+月)?(?:春|秋|夏|冬)?/g,   // dates: "2026年春", "2026年5月"
]

function isUsefulChunk(chunk: Chunk): boolean {
  const text = chunk.text.trim()
  if (text.length < 40) return false
  for (const pattern of USELESS_PATTERNS) {
    if (pattern.test(text)) return false
  }
  if (chunk.title && chunk.title.trim() === text) return false

  // Check if the chunk is mostly noise (cover page, header lines)
  const lines = text.split('\n')
  const noiseLines = lines.filter(line => {
    const trimmed = line.trim()
    return NOISE_LINE_PATTERNS.some(p => p.test(trimmed)) ||
      // Also detect inline noise (dates embedded with page numbers etc.)
      INLINE_NOISE_PATTERNS.some(p => {
        const re = new RegExp(p.source, p.flags)
        return re.test(trimmed) && trimmed.replace(re, '').trim().length < 3
      })
  })
  // If more than half the lines are noise, filter it out
  if (lines.length > 0 && noiseLines.length / lines.length > 0.5) {
    return false
  }

  return true
}

function cleanChunkText(text: string): string {
  // Remove noise lines from within chunk text
  const lines = text.split('\n')
  const cleaned = lines.filter(line => {
    const trimmed = line.trim()
    if (!trimmed) return true // keep blank lines for formatting
    return !NOISE_LINE_PATTERNS.some(p => p.test(trimmed))
  })
  // Apply inline noise removal (dates, bibliographic refs) within surviving lines
  const deNoised = cleaned.map(line =>
    INLINE_NOISE_PATTERNS.reduce((l, p) => l.replace(p, ''), line)
  )
  // Collapse multiple blank lines into one
  const result = deNoised.join('\n').replace(/\n{3,}/g, '\n\n')
  return result.trim()
}

function filterUsefulChunks(raw: Chunk[]): Chunk[] {
  const filtered = raw.filter(isUsefulChunk).map(c => ({
    ...c,
    text: cleanChunkText(c.text),
  }))
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
// Dynamic: populated from the current course's knowledge points. Empty by
// default → no highlighting until knowledge points are loaded. This avoids
// hardcoding course-specific terms (e.g. networking-only vocabulary).
const keyTerms = ref<string[]>([])

function highlightTerms(text: string): string {
  const escapeHtml = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  let result = escapeHtml(text)
  if (keyTerms.value.length === 0) return result
  // Sort by length descending to avoid partial matches
  const sortedTerms = [...keyTerms.value].sort((a, b) => b.length - a.length)
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

// Fetch knowledge points for the current course and derive highlight terms
// from their titles. Called after chunks are loaded. If the request fails or
// the course has no knowledge points, keyTerms stays empty (no highlighting).
async function loadKeyTerms() {
  try {
    const { data } = await listKnowledgePoints(courseId.value)
    const kps = data.items || []
    keyTerms.value = kps
      .map((kp) => kp.title)
      .filter((t: string) => t.length >= 2 && t.length <= 20)
  } catch {
    // Leave keyTerms empty on failure — highlighting is best-effort.
    keyTerms.value = []
  }
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
    const question = `请根据以下选取的前 20 个课程资料片段，生成一份结构化内容速览。请明确说明这不是对整份资料的完整覆盖，并包含：
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
      // Parse knowledge point source chunk IDs for filtering BEFORE loadChunks
      const qKpSourceChunkIds = route.query.kp_source_chunk_ids
      if (qKpSourceChunkIds && typeof qKpSourceChunkIds === 'string') {
        try {
          const ids = JSON.parse(qKpSourceChunkIds) as number[]
          if (Array.isArray(ids) && ids.length > 0) {
            kpSourceChunkIds.value = new Set(ids)
            kpFilterActive.value = true
          }
        } catch {
          // ignore parse errors
        }
      }

      const queryMaterialId = route.query.material_id
        ? Number(route.query.material_id)
        : null
      const match = queryMaterialId
        ? materials.value.find((m) => m.id === queryMaterialId)
        : null
      selectedMaterialId.value = match ? match.id : materials.value[0].id
      await loadChunks()
      // Load knowledge-point terms for highlighting (course-level, non-blocking).
      loadKeyTerms()

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

      // Knowledge point focus from outline
      const qKpTitle = route.query.kp_title
      const qKpSummary = route.query.kp_summary
      if (qKpTitle && typeof qKpTitle === 'string') {
        kpTitle.value = qKpTitle
        kpSummary.value = (qKpSummary as string) || ''
        // Prepare, but do not automatically send, a potentially billable AI
        // request. The learner explicitly starts it from the focus banner.
        inputQuestion.value = `请详细讲解知识点「${kpTitle.value}」${kpSummary.value ? `，参考摘要：${kpSummary.value}` : ''}`
      }
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取资料列表失败'))
  }
})

async function getAllMaterialChunks(materialId: number): Promise<Chunk[]> {
  const pageSize = 100
  const first = await getChunks(materialId, { page: 1, page_size: pageSize })
  const items = [...first.data.items]
  const total = first.data.total ?? items.length
  let page = 2
  while (items.length < total) {
    const { data } = await getChunks(materialId, { page, page_size: pageSize })
    if (data.items.length === 0) break
    items.push(...data.items)
    page += 1
  }
  return items
}

async function loadChunks() {
  if (!selectedMaterialId.value) return
  docLoading.value = true
  chunks.value = []
  studyGuide.value = ''
  try {
    if (kpFilterActive.value && kpSourceChunkIds.value.size > 0) {
      // Knowledge point filter active: load chunks from ALL materials
      // and filter by source chunk IDs, so the user sees content from
      // whichever material(s) the knowledge point was derived from.
      const allChunks: Chunk[] = []
      let bestMaterialId = selectedMaterialId.value
      let bestMatchCount = 0
      for (const m of materials.value) {
        try {
          const materialChunks = await getAllMaterialChunks(m.id)
          const matchCount = materialChunks.filter((c: Chunk) =>
            kpSourceChunkIds.value.has(c.id),
          ).length
          if (matchCount > bestMatchCount) {
            bestMatchCount = matchCount
            bestMaterialId = m.id
          }
          allChunks.push(...materialChunks)
        } catch {
          // skip materials that fail to load
        }
      }
      selectedMaterialId.value = bestMaterialId
      rawChunks.value = allChunks
      const filtered = filterUsefulChunks(allChunks).filter((c: Chunk) =>
        kpSourceChunkIds.value.has(c.id),
      )
      chunks.value = filtered
    } else {
      const materialChunks = await getAllMaterialChunks(selectedMaterialId.value)
      rawChunks.value = materialChunks
      chunks.value = filterUsefulChunks(materialChunks)
    }
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

function askAboutKnowledgePoint() {
  if (!kpTitle.value) return
  inputQuestion.value = `请详细讲解知识点「${kpTitle.value}」${kpSummary.value ? `，参考摘要：${kpSummary.value}` : ''}`
  mobilePane.value = 'assistant'
  askQuestion()
}

async function askQuestion() {
  const question = inputQuestion.value.trim()
  if (!question || aiLoading.value) return

  aiMessages.value.push({ role: 'user', content: question })
  inputQuestion.value = ''
  selectedText.value = ''
  aiLoading.value = true

  abortController.value = new AbortController()

  await nextTick()
  scrollToBottom()

  try {
    const convId = await ensureConversation()
    // If the user stopped generation during conversation creation, bail out
    if (!abortController.value) return
    const { data } = await sendMessage(
      {
        course_id: courseId.value,
        conversation_id: convId,
        question,
      },
      { signal: abortController.value.signal },
    )
    const result = data as ChatResult
    aiMessages.value.push({
      role: 'assistant',
      content: result.answer,
      citations: result.citations,
    })
  } catch (err) {
    // axios cancels via AbortController produce a CanceledError with
    // name 'CanceledError' / code 'ERR_CANCELED'; native AbortController
    // uses name 'AbortError'. Handle both silently.
    const isAborted =
      err instanceof Error &&
      (err.name === 'AbortError' ||
        err.name === 'CanceledError' ||
        (err as { code?: string }).code === 'ERR_CANCELED')
    if (isAborted) {
      // Keep partial content if any — request was cancelled by the user
    } else {
      aiMessages.value.push({
        role: 'assistant',
        content: `抱歉，回答生成失败：${parseApiError(err, '请稍后重试')}`,
      })
    }
  } finally {
    aiLoading.value = false
    abortController.value = null
    await nextTick()
    scrollToBottom()
  }
}

function stopAiGeneration() {
  if (abortController.value) {
    abortController.value.abort()
    abortController.value = null
    aiLoading.value = false
  }
}

function clearAiConversation() {
  aiMessages.value = []
  conversationId.value = null
}

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

function renderAnswer(text: string): string {
  return renderMarkdown(text)
}

// Copy an AI answer's raw content to the clipboard.
async function copyMessage(content: string) {
  try {
    await navigator.clipboard.writeText(content)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择文本复制')
  }
}

function goBack() {
  router.push(`/courses/${courseId.value}`)
}
</script>

<style scoped>
.learn-page {
  display: flex;
  flex-direction: column;
  height: calc(100dvh - 136px);
  min-height: 620px;
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

.material-select {
  width: 240px;
}

.mobile-pane-switch {
  display: none;
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

.toc-item:focus-visible {
  outline-offset: -3px;
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

/* Knowledge point focus banner */
.kp-focus-banner {
  margin-bottom: 24px;
  background: linear-gradient(135deg, #fdf6ec 0%, #fef0f0 100%);
  border: 1px solid #f5dab1;
  border-radius: 10px;
  padding: 12px 16px;
}

.kp-focus-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #e6a23c;
}

.kp-focus-head .el-button {
  margin-left: auto;
}

.kp-focus-title {
  flex: 1;
}

.kp-focus-summary {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.6;
  color: #606266;
}

.kp-filter-note {
  margin-top: 6px;
  font-size: 12px;
  color: #67c23a;
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

/* Chunk images */
.doc-chunk-images {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.doc-chunk-image-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
  background: #fafafa;
  padding: 8px;
}

.image-placeholder,
.image-error {
  padding: 20px;
  text-align: center;
  color: #909399;
  font-size: 13px;
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
  flex-direction: column;
  gap: 8px;
}

.ai-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}

.ai-input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.ai-input-area .el-button {
  flex-shrink: 0;
}

/* Copy button row below AI assistant answers */
.ai-msg-actions {
  margin-top: 6px;
  display: flex;
  gap: 4px;
}

.ai-msg-actions .el-button {
  padding: 2px 6px;
  color: #909399;
}

.ai-msg-actions .el-button:hover {
  color: #409eff;
}

.ai-msg-actions .el-icon {
  margin-right: 2px;
}

/* Markdown rendered AI content. v-html content is not scoped, so we
   target descendants with :deep(). Shared by the study guide card and
   the AI assistant message bubbles. */
.markdown-content {
  white-space: normal;
  font-size: 14px;
  line-height: 1.7;
}

.markdown-content :deep(p) {
  margin: 0.5em 0;
}

.markdown-content :deep(p:first-child) {
  margin-top: 0;
}

.markdown-content :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4),
.markdown-content :deep(h5),
.markdown-content :deep(h6) {
  margin: 0.8em 0 0.4em;
  font-weight: 600;
  line-height: 1.4;
}

.markdown-content :deep(h1) {
  font-size: 1.4em;
}

.markdown-content :deep(h2) {
  font-size: 1.25em;
}

.markdown-content :deep(h3) {
  font-size: 1.1em;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin: 0.5em 0;
  padding-left: 1.5em;
}

.markdown-content :deep(li) {
  margin: 0.2em 0;
}

.markdown-content :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 0.15em 0.4em;
  border-radius: 3px;
  font-size: 0.9em;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
}

.markdown-content :deep(pre) {
  margin: 0.6em 0;
  padding: 12px;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 6px;
  overflow-x: auto;
}

.markdown-content :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
  font-size: 0.9em;
}

.markdown-content :deep(blockquote) {
  margin: 0.5em 0;
  padding: 0.2em 0.9em;
  border-left: 3px solid #dcdfe6;
  color: #606266;
  background: #fafafa;
}

.markdown-content :deep(a) {
  color: #409eff;
  text-decoration: none;
}

.markdown-content :deep(a:hover) {
  text-decoration: underline;
}

.markdown-content :deep(table) {
  border-collapse: collapse;
  margin: 0.6em 0;
  width: 100%;
  font-size: 0.95em;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  border: 1px solid #dcdfe6;
  padding: 6px 10px;
  text-align: left;
}

.markdown-content :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
}

.markdown-content :deep(hr) {
  border: none;
  border-top: 1px solid #dcdfe6;
  margin: 1em 0;
}

.markdown-content :deep(img) {
  max-width: 100%;
}

@media (max-width: 1180px) {
  .doc-toc {
    width: 176px;
  }
  .ai-assistant {
    width: 320px;
  }
  .doc-reader {
    padding: 20px;
  }
}

/* Mobile uses an explicit three-pane switch so each task keeps a useful
   viewport instead of stacking three independently scrolling panels. */
@media (max-width: 768px) {
  .learn-page {
    height: calc(100dvh - 120px);
    min-height: 560px;
  }

  .learn-header {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 10px;
    padding: 10px 12px;
  }

  .learn-header > :deep(.el-button) {
    margin-left: 0;
  }

  .learn-title {
    min-width: 0;
    align-self: center;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .material-select {
    width: 100%;
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .learn-header > :deep(.el-button:nth-of-type(2)) {
    grid-column: 1 / -1;
    grid-row: 3;
    width: 100%;
  }

  .mobile-pane-switch {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 4px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-base);
    background: #fff;
  }

  .mobile-pane-switch button {
    min-height: 40px;
    border: 0;
    border-radius: 8px;
    background: #f2f4f7;
    color: var(--text-regular);
    font: inherit;
    cursor: pointer;
  }

  .mobile-pane-switch button.active {
    background: #e8efff;
    color: var(--color-primary);
    font-weight: 600;
  }

  .learn-body {
    display: block;
    min-height: 0;
  }

  .mobile-hidden {
    display: none !important;
  }

  .doc-toc {
    width: 100%;
    height: 100%;
    max-height: none;
    border-right: none;
    border-bottom: 0;
    overflow-y: auto;
  }

  .toc-item {
    min-height: 44px;
  }

  .doc-reader {
    width: 100%;
    height: 100%;
    padding: 14px 12px;
    overflow-y: auto;
  }

  .doc-chunk {
    padding: 14px;
  }

  .doc-chunk-head,
  .study-guide-head,
  .kp-focus-head {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .study-guide-head .el-button,
  .kp-focus-head .el-button {
    margin-left: 0;
  }

  .kp-focus-title {
    flex-basis: calc(100% - 40px);
  }

  .ai-assistant {
    width: 100%;
    height: 100%;
    max-height: none;
    border-left: none;
    border-top: 0;
  }

  .ai-messages {
    min-height: 0;
  }

  .ai-input-area {
    padding-bottom: max(12px, env(safe-area-inset-bottom));
  }
}
</style>
