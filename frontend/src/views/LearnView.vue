<template>
  <div class="learn-page">
    <!-- Header -->
    <div class="learn-header">
      <el-button link @click="goBack">
        <el-icon><ArrowLeft /></el-icon>
        返回课程
      </el-button>
      <el-button
        v-if="fromTaskId"
        link
        type="primary"
        @click="goBackToPlan"
      >
        <el-icon><ArrowLeft /></el-icon>
        返回计划
      </el-button>
      <el-button v-if="fromTaskId" type="success" size="small" @click="confirmTaskLearning">完成本次学习</el-button>
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
        @change="handleMaterialChange"
      >
        <el-option
          v-for="m in materials"
          :key="m.id"
          :label="m.filename"
          :value="m.id"
        />
      </el-select>
      <el-radio-group v-model="readerMode" size="small" aria-label="资料展示模式">
        <el-radio-button label="page">原页</el-radio-button>
        <el-radio-button label="clean">结构化文本</el-radio-button>
        <el-radio-button label="raw">原文</el-radio-button>
      </el-radio-group>
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
            v-for="(page, idx) in materialPages"
            :key="page.catalog_key"
            class="toc-item"
            :class="{ active: activeChunkIndex === idx }"
            role="button"
            tabindex="0"
            @click="scrollToPage(page.page_no)"
            @keydown.enter="scrollToPage(page.page_no)"
            @keydown.space.prevent="scrollToPage(page.page_no)"
          >
            <span class="toc-num">{{ page.page_no }}</span>
            <div class="toc-text">
              <span class="toc-title">{{ derivePageTitle(page) }}</span>
              <el-tag
                size="small"
                :type="pageTypeTagType(page.page_type)"
                effect="plain"
                class="toc-type-tag"
              >
                {{ pageTypeLabel(page.page_type) }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- Center: Document reader -->
      <div class="doc-reader" :class="{ 'mobile-hidden': mobilePane !== 'content' }" @scroll="handleDocScroll">
        <div v-if="docLoading" class="doc-loading" role="status" aria-live="polite">
          <el-icon class="is-loading"><Loading /></el-icon>
          加载资料中...
        </div>
        <div v-else-if="chunks.length === 0 && materialPages.length === 0" class="doc-empty">
          <el-empty description="请选择一份资料开始学习" :image-size="100" />
        </div>
        <div v-else class="doc-content">
          <div v-if="readiness && !readiness.usable" class="image-error-banner" data-testid="material-readiness-blocked">
            <el-alert type="warning" :closable="false" show-icon>
              <template #title>
                <span>资料尚未完全可读：{{ readiness.blocking_reasons.join('、') }}</span>
              </template>
              <el-button
                v-if="readiness.file_type === 'pdf' && readiness.missing_page_numbers.length > 0"
                type="warning"
                size="small"
                :loading="reextractingImages"
                @click="handleRepairDocument"
              >
                修复文档预览
              </el-button>
            </el-alert>
          </div>
          <div v-if="readiness?.page_catalog_synthetic_numbers?.length" class="image-info-banner" data-testid="legacy-page-catalog-repair">
            <el-alert type="info" :closable="false" show-icon>
              <template #title>
                <span>检测到 {{ readiness.page_catalog_synthetic_numbers.length }} 页旧资料目录记录，建议持久化修复预览。</span>
              </template>
              <el-button type="primary" size="small" :loading="reextractingImages" @click="handleRepairDocument">
                修复文档预览
              </el-button>
            </el-alert>
          </div>
          <div class="image-filter-control">
            <el-switch
              v-model="showFilteredImages"
              size="small"
              active-text="显示已过滤图片"
              @change="loadChunks"
            />
          </div>

          <!-- V7.5.1-03: non-blocking hint when page fallback is ready -->
          <div v-if="brokenImageIds.size > 0 && imageIntegrityData?.status === 'page_fallback_ready'" class="image-info-banner">
            <el-alert type="info" :closable="false" show-icon>
              <template #title>
                <span>独立图片不可拆分，已使用原页预览（{{ imageIntegrityData?.ready_pages || 0 }}/{{ imageIntegrityData?.expected_pages || 0 }} 页可读）</span>
              </template>
              <el-button
                type="primary"
                size="small"
                :loading="reextractingImages"
                @click="handleRepairDocument"
              >
                修复文档预览
              </el-button>
            </el-alert>
          </div>

          <!-- V6-14: image error banner with re-extract button (only when NOT page_fallback_ready) -->
          <div v-else-if="brokenImageIds.size > 0 && imageIntegrityData?.status !== 'page_fallback_ready'" class="image-error-banner">
            <el-alert type="warning" :closable="false" show-icon>
              <template #title>
                <span>检测到 {{ brokenImageIds.size }} 张图片缺失，页图也不可用，文档可能无法完整阅读</span>
              </template>
              <el-button
                type="warning"
                size="small"
                :loading="reextractingImages"
                @click="handleRepairDocument"
              >
                修复文档预览
              </el-button>
            </el-alert>
          </div>

          <!-- AI Study Guide -->
          <div v-if="studyGuide || studyGuideLoading" class="study-guide-card">
            <div class="study-guide-head">
              <el-icon color="#409eff"><MagicStick /></el-icon>
              <span>AI 内容速览</span>
              <el-tag size="small" type="info" effect="plain">基于抽样课程证据</el-tag>
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
                <div v-if="studyGuideCoverage" class="study-guide-coverage">{{ studyGuideCoverage }}</div>
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

          <PageCanvas v-if="readerMode === 'page'" :pages="materialPages" />
          <PageTextPanel v-else-if="readerMode === 'raw'" :pages="materialPages" mode="raw" @select="handleSelection" />
          <!-- Clean mode renders semantic chunks once; do not duplicate page.clean_text. -->
          <div v-else class="doc-chunks" @mouseup="handleSelection">
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
                <span
                  v-if="chunk.quality_score !== null && chunk.quality_score !== undefined"
                  class="quality-badge"
                  :class="getQualityClass(chunk.quality_score)"
                  :title="chunk.quality_reason || ''"
                >
                  AI 质量 {{ Math.round(chunk.quality_score * 100) }}%
                </span>
                <span
                  v-if="parseNoiseFlags(chunk.noise_flags)"
                  class="noise-badge"
                  :title="formatNoiseTooltip(chunk.noise_flags)"
                >
                  {{ formatNoiseLabel(chunk.noise_flags) }}
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
                  <div v-if="img.is_decorative" class="image-decorative-tag">
                    <el-tag type="info" size="small" effect="plain">
                      已过滤：{{ img.decorative_reason || '装饰性图片' }}
                    </el-tag>
                  </div>
                  <el-image
                    :src="imageUrls[img.id] || ''"
                    :preview-src-list="imageUrls[img.id] ? [imageUrls[img.id]] : []"
                    :alt="`${materials.find((m) => m.id === selectedMaterialId)?.filename || '课程资料'}第 ${chunk.page_no || '?'} 页插图`"
                    fit="contain"
                    style="max-width: 100%; max-height: 400px; border-radius: 6px;"
                    loading="lazy"
                    @error="handleImageError(img.id)"
                  >
                    <template #placeholder>
                      <div class="image-placeholder">图片加载中...</div>
                    </template>
                    <template #error>
                      <div class="image-error image-missing">
                        <el-icon><PictureRounded /></el-icon>
                        <span>图片缺失</span>
                      </div>
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
import { nextTick, onBeforeUnmount, onMounted, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ChatDotRound, CopyDocument, InfoFilled, Loading, MagicStick, Aim, PictureRounded } from '@element-plus/icons-vue'
import { listMaterials, getChunks, getMaterialPages, getMaterialReadiness, generateMaterialStudyGuide, reextractImages, getImageIntegrity, rebuildPageAssets, type Material, type Chunk, type MaterialPage, type MaterialReadiness, type ImageIntegrityResult } from '../api/material'
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
import request from '../api'
import { recordTaskEvent, verifyTask } from '../api/plan'
import PageCanvas from '../components/document/PageCanvas.vue'
import PageTextPanel from '../components/document/PageTextPanel.vue'

const route = useRoute()
const router = useRouter()

const courseId = computed(() => Number(route.params.id))
const courseName = ref('')
// PLAN-V3-03: track if we navigated here from a plan task
const fromTaskId = computed(() => {
  const tid = Number(route.query.task_id)
  return Number.isInteger(tid) && tid > 0 ? tid : null
})
const targetLoadRecorded = ref(false)
const materials = ref<Material[]>([])
const selectedMaterialId = ref<number | null>(null)
const rawChunks = ref<Chunk[]>([])
const chunks = ref<Chunk[]>([])
const materialPages = ref<MaterialPage[]>([])
const readerMode = ref<'clean' | 'raw' | 'page'>('page')
const selectedMaterial = computed(() => materials.value.find((item) => item.id === selectedMaterialId.value) || null)
const imageUrls = ref<Record<number, string>>({})
const showFilteredImages = ref(false)
const docLoading = ref(false)
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
const studyGuideCoverage = ref('')

// Knowledge point focus (from outline navigation)
const kpTitle = ref('')
const kpSummary = ref('')
const kpSourceChunkIds = ref<Set<number>>(new Set())
const kpFilterActive = ref(false)

// TOC + progress state
const activeChunkIndex = ref(0)
const readProgress = ref(0)

// V6-14: image error isolation + re-extraction
const brokenImageIds = ref<Set<number>>(new Set())
const reextractingImages = ref(false)
const imageIntegrityStatus = ref<string>('')
const imageIntegrityData = ref<ImageIntegrityResult | null>(null)
const readiness = ref<MaterialReadiness | null>(null)

function releaseImageUrls() {
  Object.values(imageUrls.value).forEach((url) => URL.revokeObjectURL(url))
  imageUrls.value = {}
}

// V6-14: derive a human-readable page title from the first heading block
function derivePageTitle(page: MaterialPage): string {
  try {
    const blocks = JSON.parse(page.blocks || '[]')
    if (Array.isArray(blocks)) {
      const heading = blocks.find(
        (b: { block_type?: string; text?: string }) => b.block_type === 'heading' && b.text,
      )
      if (heading && heading.text) {
        return heading.text.trim().substring(0, 40)
      }
    }
  } catch {
    // ignore parse errors
  }
  return `第 ${page.page_no} 页`
}

function pageTypeLabel(pageType: string): string {
  switch (pageType) {
    case 'image_only':
      return '纯图'
    case 'mixed':
      return '图文'
    case 'text':
    default:
      return '文本'
  }
}

function pageTypeTagType(pageType: string): 'info' | 'warning' | 'success' {
  switch (pageType) {
    case 'image_only':
      return 'warning'
    case 'mixed':
      return 'success'
    case 'text':
    default:
      return 'info'
  }
}

function getQualityClass(score: number): string {
  if (score >= 0.7) return 'quality-high'
  if (score >= 0.4) return 'quality-medium'
  return 'quality-low'
}

// LEARN-V3-01: noise_flags display helpers
function parseNoiseFlags(noiseFlags: string | null | undefined): Record<string, boolean> | null {
  if (!noiseFlags) return null
  try {
    const parsed = JSON.parse(noiseFlags)
    if (parsed && typeof parsed === 'object') {
      // Only show if at least one flag is true
      const hasNoise = Object.values(parsed).some((v) => v === true)
      return hasNoise ? parsed : null
    }
  } catch {
    // ignore parse errors
  }
  return null
}

function formatNoiseLabel(noiseFlags: string | null | undefined): string {
  const flags = parseNoiseFlags(noiseFlags)
  if (!flags) return ''
  const labels: string[] = []
  if (flags.line_repetition) labels.push('重复行')
  if (flags.short_line_stacking) labels.push('短行堆叠')
  if (flags.low_diversity) labels.push('低多样性')
  return labels.length > 0 ? `噪音：${labels.join('、')}` : ''
}

function formatNoiseTooltip(noiseFlags: string | null | undefined): string {
  const flags = parseNoiseFlags(noiseFlags)
  if (!flags) return ''
  const reasons: string[] = []
  if (flags.line_repetition) reasons.push('行重复率 > 50%')
  if (flags.short_line_stacking) reasons.push('短行（<4字符）占比 > 60%')
  if (flags.low_diversity) reasons.push('词汇多样性 < 0.3')
  return reasons.join('；')
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
  if (!selectedMaterialId.value || chunks.value.length === 0) return
  studyGuideLoading.value = true
  studyGuide.value = ''
  studyGuideCoverage.value = ''
  try {
    const { data } = await generateMaterialStudyGuide(selectedMaterialId.value)
    studyGuide.value = data.answer
    studyGuideCoverage.value = data.coverage_note
  } catch (err) {
    ElMessage.error(parseApiError(err, '学习指南生成失败'))
  } finally {
    studyGuideLoading.value = false
  }
}

// --- Scroll + progress ---
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

      const publicMaterial = typeof route.query.material === 'string' ? route.query.material : null
      const queryMaterialId = route.query.material_id ? Number(route.query.material_id) : null
      const match = publicMaterial
        ? materials.value.find((m) => m.public_id === publicMaterial)
        : queryMaterialId ? materials.value.find((m) => m.id === queryMaterialId) : null
      selectedMaterialId.value = match ? match.id : materials.value[0].id
      syncPublicMaterialRoute()
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

async function getAllMaterialChunks(
  materialId: number,
  includeDecorative = showFilteredImages.value,
): Promise<Chunk[]> {
  const pageSize = 100
  const first = await getChunks(materialId, {
    page: 1,
    page_size: pageSize,
    include_decorative: includeDecorative,
  })
  const items = [...first.data.items]
  const total = first.data.total ?? items.length
  let page = 2
  while (items.length < total) {
    const { data } = await getChunks(materialId, {
      page,
      page_size: pageSize,
      include_decorative: includeDecorative,
    })
    if (data.items.length === 0) break
    items.push(...data.items)
    page += 1
  }
  return items
}

function syncPublicMaterialRoute() {
  const material = selectedMaterial.value
  if (!material || route.query.material === material.public_id) return
  const query: Record<string, string | undefined> = { ...route.query, material: material.public_id }
  delete query.material_id
  router.replace({ query })
}

async function handleMaterialChange() {
  syncPublicMaterialRoute()
  await loadChunks()
}

async function loadChunks() {
  if (!selectedMaterialId.value) return
  releaseImageUrls()
  brokenImageIds.value.clear()
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
      const filtered = allChunks.filter((c: Chunk) =>
        kpSourceChunkIds.value.has(c.id),
      )
      chunks.value = filtered
      // V7.5.1-04: load materialPages for the best-matching material so
      // the default page mode has data to render.
      try {
        materialPages.value = (await getMaterialPages(bestMaterialId)).data.items
      } catch {
        materialPages.value = []
      }
      readiness.value = (await getMaterialReadiness(bestMaterialId)).data
      readerMode.value = readiness.value.reader_mode === 'page' ? 'page' : 'clean'
    } else {
      const [readinessResponse, materialChunks] = await Promise.all([
        getMaterialReadiness(selectedMaterialId.value),
        getAllMaterialChunks(selectedMaterialId.value),
      ])
      readiness.value = readinessResponse.data
      rawChunks.value = materialChunks
      // The backend is the single source of truth for cleaned/displayable
      // content; do not hide a valid citation with a second UI heuristic.
      chunks.value = materialChunks
      materialPages.value = (await getMaterialPages(selectedMaterialId.value)).data.items
      // The server owns the capability contract.  A scanned PDF is page
      // readable even when it has no text chunks; a text material must never
      // select an empty page canvas merely because a stale asset exists.
      readerMode.value = readiness.value.reader_mode === 'page' ? 'page' : 'clean'
    }
    await preloadImages(chunks.value)
    // V6-52: load image integrity status (best-effort, non-blocking)
    loadImageIntegrity()
    // V7: task start only creates the in-progress state.  Evidence is sent
    // after the target material and its rendered reader data have loaded.
    // Route URLs use the immutable public identity, while task-event
    // evidence intentionally retains the resolved numeric primary key.
    const expectedMaterialId = typeof route.query.material === 'string'
      ? (selectedMaterial.value?.id ?? 0)
      : Number(route.query.material_id)
    if (
      fromTaskId.value &&
      !targetLoadRecorded.value &&
      Number.isInteger(expectedMaterialId) &&
      expectedMaterialId > 0 &&
      selectedMaterialId.value === expectedMaterialId &&
      selectedMaterial.value?.status === 'ready' &&
      (chunks.value.length > 0 || materialPages.value.length > 0)
    ) {
      await recordTaskEvent(
        fromTaskId.value,
        'target_loaded',
        expectedMaterialId,
        selectedMaterial.value.active_version_id ?? undefined,
        route.fullPath,
        materialPages.value.length || chunks.value.length,
      )
      targetLoadRecorded.value = true
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取资料内容失败'))
  } finally {
    docLoading.value = false
  }
}

onBeforeUnmount(releaseImageUrls)

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

async function preloadImages(source: Chunk[]) {
  const images = source.flatMap((chunk) => chunk.images || [])
  await Promise.allSettled(images.map(async (image) => {
    if (!image.file_url || imageUrls.value[image.id]) return
    try {
      const { data } = await request.get(image.file_url, { responseType: 'blob' })
      imageUrls.value[image.id] = URL.createObjectURL(data)
      brokenImageIds.value.delete(image.id)
    } catch {
      brokenImageIds.value.add(image.id)
    }
  }))
}

// V6-14: handle individual image load errors from el-image
function handleImageError(imgId: number) {
  brokenImageIds.value.add(imgId)
}

// V6-52: load image integrity status for the selected material
async function loadImageIntegrity() {
  if (!selectedMaterialId.value) return
  try {
    const { data } = await getImageIntegrity(selectedMaterialId.value)
    imageIntegrityStatus.value = data.status
    imageIntegrityData.value = data
  } catch {
    imageIntegrityStatus.value = ''
    imageIntegrityData.value = null
  }
}

// V7.5.1-03: combined document repair — rebuild page assets + re-extract images
async function handleRepairDocument() {
  if (!selectedMaterialId.value || reextractingImages.value) return
  reextractingImages.value = true
  try {
    const { data: rebuilt } = await rebuildPageAssets(selectedMaterialId.value)
    if (rebuilt.status === 'readable_but_not_repaired') {
      ElMessage.warning('当前原页仍可阅读，但页面目录持久化失败。下次启动可能需要再次修复。')
      return
    }
    if (rebuilt.status !== 'ready' || rebuilt.reader_state !== 'fully_repaired' || rebuilt.page_catalog_backfill.status !== 'success' || rebuilt.page_catalog_backfill.remaining_synthetic_page_numbers.length > 0) {
      ElMessage.error('文档预览修复失败，已保留修复前可读版本。')
      return
    }

    // Step 2: Re-extract standalone images
    let imgExtracted = 0
    let imageReextractState: 'success' | 'skipped' | 'failed' = 'success'
    try {
      const { data: result } = await reextractImages(selectedMaterialId.value)
      if (result.status === 'forbidden') {
        imageReextractState = 'skipped'
      } else if (result.status === 'missing') {
        imageReextractState = 'skipped'
      } else {
        imgExtracted = result.extracted ?? 0
      }
    } catch (err) {
      imageReextractState = 'failed'
      console.warn('Standalone image re-extraction failed after page repair', err)
    }

    // Refresh all three server-owned facts before reporting success.
    brokenImageIds.value.clear()
    try {
      await loadChunks()
      await loadImageIntegrity()
    } catch (err) {
      console.warn('Unable to confirm repair state after refresh', err)
      ElMessage.warning('原页已修复，但无法确认最终状态，请刷新后重试。')
      return
    }
    const current = readiness.value
    const effective = current?.effective_page_count ?? 0
    const expected = current?.expected_page_count ?? 0
    if (current?.usable && effective === expected && expected > 0 && current.page_catalog_synthetic_numbers.length === 0) {
      if (imageReextractState === 'failed') {
        ElMessage.warning('原页已修复，但独立图片提取失败。')
      } else if (imageReextractState === 'skipped') {
        ElMessage.success(`原页预览和页面目录已修复：${effective}/${expected} 页可读（独立图片无需提取）。`)
      } else {
        ElMessage.success(`原页预览和页面目录已修复：${effective}/${expected} 页可读，提取 ${imgExtracted} 张独立图片`)
      }
    } else {
      ElMessage.warning(`文档预览尚未完整：${effective}/${expected} 页有效，请根据提示继续处理。`)
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '修复文档预览失败，旧版本仍可使用'))
  } finally {
    reextractingImages.value = false
  }
}

// V6-14: preserve scroll position when switching reader modes
watch(readerMode, async () => {
  const reader = document.querySelector('.doc-reader') as HTMLElement | null
  if (!reader) return
  const savedScrollTop = reader.scrollTop
  await nextTick()
  reader.scrollTop = savedScrollTop
})
function scrollToPage(pageNo: number) {
  document.getElementById(`page-${pageNo}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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

// PLAN-V3-03: Navigate back to the plans page
function goBackToPlan() {
  router.push({ name: 'plans', query: route.query.plan_id ? { plan_id: String(route.query.plan_id) } : {} })
}

async function confirmTaskLearning() {
  if (!fromTaskId.value) return
  try {
    const { data } = await verifyTask(fromTaskId.value, true)
    if (!data.verified) {
      ElMessage.warning('尚未满足学习完成条件，请确认已打开并阅读指定资料')
      return
    }
    ElMessage.success('学习任务已完成')
    goBackToPlan()
  } catch (err) {
    ElMessage.error(parseApiError(err, '完成学习失败'))
  }
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

.toc-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.toc-type-tag {
  align-self: flex-start;
  font-size: 10px;
  height: 18px;
  line-height: 16px;
  padding: 0 4px;
}

/* V6-14: image error banner */
.image-error-banner {
  margin-bottom: 16px;
}

.image-error-banner .el-alert__content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

/* V7.5.1-03: non-blocking image info banner */
.image-info-banner {
  margin-bottom: 16px;
}

.image-info-banner .el-alert__content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

/* V6-14: missing image placeholder */
.image-missing {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 20px;
  color: #909399;
  background: #f5f7fa;
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
}

.image-missing .el-icon {
  font-size: 32px;
  color: #c0c4cc;
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

.image-filter-control {
  display: flex;
  justify-content: flex-end;
  margin: -8px 0 12px;
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

.study-guide-coverage {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #f4f7fb;
  color: #606266;
  font-size: 13px;
  line-height: 1.5;
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

.quality-badge {
  margin-left: auto;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
  cursor: help;
}

.noise-badge {
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  background: #f56c6c22;
  color: #f56c6c;
  border: 1px solid #f56c6c44;
  cursor: help;
}
.image-decorative-tag {
  margin-bottom: 4px;
}

.quality-high {
  background: #e8f5e9;
  color: #2e7d32;
  border: 1px solid #a5d6a7;
}

.quality-medium {
  background: #fff3e0;
  color: #e65100;
  border: 1px solid #ffcc80;
}

.quality-low {
  background: #ffebee;
  color: #c62828;
  border: 1px solid #ef9a9a;
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
