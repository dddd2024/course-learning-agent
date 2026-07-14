<script setup lang="ts">
// Display-only evidence drawer. Shows either citation detail (with the
// full chunk text and highlighted quote) or the retrieval process list.
// The parent owns all state; this component renders and emits follow-up
// selections and visibility changes.
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { Citation } from '../../api/chat'
import type { ChunkDetail } from '../../api/material'
import type { ChatMessage } from './types'
import FollowUpSuggestions from './FollowUpSuggestions.vue'

const props = defineProps<{
  visible: boolean
  loading: boolean
  citation: Citation | null
  message: ChatMessage | null
  chunk: ChunkDetail | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'follow-up', question: string): void
}>()

const router = useRouter()

const drawerTitle = computed(() => {
  if (props.citation) return '引用详情'
  return '检索过程'
})

function truncate(text: string, max = 120): string {
  if (!text) return ''
  return text.length > max ? text.slice(0, max) + '…' : text
}

function goToLearn(chunkId: number, materialPublicId?: string | null) {
  if (props.message?.courseId) {
    router.push({
      path: `/courses/${props.message.courseId}/learn`,
      query: {
        ...(materialPublicId ? { material: materialPublicId } : {}),
        chunk_id: String(chunkId),
      },
    })
    emit('update:visible', false)
  }
}

// Render chunk text with quote_text highlighted. Escapes HTML first,
// then wraps the quote (if found) in <mark>. When the quote is not an
// exact substring, the full context is shown without highlighting.
function renderHighlightedText(fullText: string, quote: string): string {
  if (!fullText) return ''
  const escapeHtml = (s: string) =>
    s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
  const escaped = escapeHtml(fullText)
  if (!quote || quote.length < 2) return escaped
  const escapedQuote = escapeHtml(quote.trim())
  const idx = escaped.indexOf(escapedQuote)
  if (idx !== -1) {
    return (
      escaped.slice(0, idx) +
      '<mark class="citation-highlight">' +
      escapedQuote +
      '</mark>' +
      escaped.slice(idx + escapedQuote.length)
    )
  }
  const shortQuote = escapedQuote.slice(0, 20)
  if (shortQuote.length >= 4) {
    const shortIdx = escaped.indexOf(shortQuote)
    if (shortIdx !== -1) {
      return (
        escaped.slice(0, shortIdx) +
        '<mark class="citation-highlight">' +
        shortQuote +
        '</mark>' +
        escaped.slice(shortIdx + shortQuote.length)
      )
    }
  }
  return escaped
}
</script>

<template>
  <el-drawer
    :model-value="props.visible"
    :title="drawerTitle"
    direction="rtl"
    size="480px"
    @update:model-value="emit('update:visible', $event)"
  >
    <div v-loading="props.loading" class="drawer-body">
      <template v-if="props.citation">
        <div class="drawer-section">
          <div class="drawer-label">资料名称</div>
          <div class="drawer-value">{{ props.citation.material_name }}</div>
        </div>
        <div class="drawer-section">
          <div class="drawer-label">页码</div>
          <div class="drawer-value">
            {{ props.citation.page_no !== null && props.citation.page_no !== undefined ? `第 ${props.citation.page_no} 页` : '未标注' }}
          </div>
        </div>
        <div class="drawer-section">
          <div class="drawer-label">原文片段</div>
          <div
            v-if="props.chunk"
            class="drawer-chunk-text"
            v-html="renderHighlightedText(props.chunk.text, props.citation.quote_text)"
          />
          <div v-else class="drawer-quote">{{ props.citation.quote_text }}</div>
        </div>
        <div class="drawer-section citation-actions">
          <el-button
            type="primary"
            :disabled="!props.citation.material_public_id"
            @click="goToLearn(props.citation.chunk_id, props.citation.material_public_id)"
          >
            打开引用资料
          </el-button>
          <span v-if="!props.citation.material_public_id" class="citation-route-unavailable">
            旧引用缺少稳定资料标识，暂不能直接跳转
          </span>
        </div>
      </template>

      <div
        v-if="
          props.message?.followUpQuestions &&
          props.message.followUpQuestions.length > 0
        "
        class="drawer-section"
      >
        <div class="drawer-label">追问建议</div>
        <FollowUpSuggestions
          :questions="props.message.followUpQuestions"
          @select="emit('follow-up', $event)"
        />
      </div>

      <div class="drawer-section">
        <div class="drawer-label">
          检索命中 ({{ props.message?.retrievedChunks?.length ?? 0 }})
        </div>
        <div class="retrieval-explain">
          以下是从课程资料中检索到的相关片段。AI 根据这些片段生成回答，
          <span class="retrieval-explain-cited">已引用</span> 表示该片段被
          AI 直接引用，<span class="retrieval-explain-uncited">未引用</span>
          表示检索到但未直接使用。
        </div>
        <template
          v-if="
            props.message?.retrievedChunks &&
            props.message.retrievedChunks.length > 0
          "
        >
          <div class="retrieval-list">
            <div
              v-for="chunk in props.message.retrievedChunks"
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
              </div>
              <div class="retrieval-snippet">
                {{ truncate(chunk.snippet, 80) }}
              </div>
              <div class="retrieval-actions">
                <el-button
                  text
                  size="small"
                  type="primary"
                  @click="goToLearn(chunk.chunk_id)"
                >
                  去学习
                </el-button>
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
</template>

<style scoped>
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

.drawer-chunk-text {
  font-size: 13px;
  color: #303133;
  line-height: 1.8;
  white-space: pre-wrap;
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  max-height: 320px;
  overflow-y: auto;
  word-break: break-word;
  border-left: 3px solid #dcdfe6;
}

.drawer-chunk-text :deep(.citation-highlight) {
  background: #fff3a0;
  color: #303133;
  padding: 0 2px;
  border-radius: 2px;
  font-weight: 600;
}

.citation-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.citation-route-unavailable {
  color: #909399;
  font-size: 12px;
}

.retrieval-explain {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  margin-bottom: 10px;
  padding: 8px 10px;
  background: #f4f4f5;
  border-radius: 6px;
}

.retrieval-explain-cited {
  color: #67c23a;
  font-weight: 600;
}

.retrieval-explain-uncited {
  color: #909399;
}

.retrieval-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.retrieval-item {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px;
  background: #fafafa;
}

.retrieval-item.retrieval-cited {
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
  color: #303133;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.retrieval-meta {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}

.retrieval-snippet {
  font-size: 12px;
  line-height: 1.5;
  color: #606266;
  margin-bottom: 6px;
}

.retrieval-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
