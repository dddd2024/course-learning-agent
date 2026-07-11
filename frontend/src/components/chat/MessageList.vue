<script setup lang="ts">
// Display-only message list. Renders user/agent bubbles, citation
// capsules, retrieval buttons and follow-up suggestions. All actions
// are forwarded to the parent via events.
import {
  ChatDotRound,
  CopyDocument,
  Document,
  Loading,
  Refresh,
  User,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { Citation } from '../../api/chat'
import type { ChatMessage } from './types'
import CitationCapsules from './CitationCapsules.vue'
import FollowUpSuggestions from './FollowUpSuggestions.vue'
import { renderMarkdown } from '../../utils/markdown'
import { formatLocalDateTime } from '../../utils/datetime'

defineProps<{
  messages: ChatMessage[]
}>()

const emit = defineEmits<{
  (e: 'open-citation', citation: Citation, message: ChatMessage): void
  (e: 'open-retrieval', message: ChatMessage): void
  (e: 'follow-up', question: string): void
  (e: 'regenerate', message: ChatMessage): void
}>()

// Copy an AI message's raw markdown content to the clipboard.
// Uses the async Clipboard API and surfaces the result via ElMessage.
async function copyMessage(content: string) {
  try {
    await navigator.clipboard.writeText(content)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择文本复制')
  }
}

// Format an ISO timestamp for display under a bubble. Delegates to the
// centralized formatLocalDateTime helper so UTC-aware timestamps from the
// backend are converted to local time consistently. Returns an empty
// string for missing/invalid values so the v-if guard hides the element.
function formatTime(dt: string | null | undefined): string {
  if (!dt) return ''
  return formatLocalDateTime(dt)
}
</script>

<template>
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
          <template v-else-if="msg.role === 'agent'">
            <div class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
          </template>
          <template v-else>{{ msg.content }}</template>
        </div>

        <div v-if="formatTime(msg.createdAt)" class="msg-time">
          {{ formatTime(msg.createdAt) }}
        </div>

        <!-- T05: surface LLM fallback state so users know when an
             answer came from the mock provider rather than a real LLM. -->
        <el-alert
          v-if="msg.role === 'agent' && msg.fallbackUsed"
          type="warning"
          :closable="false"
          show-icon
          class="fallback-alert"
        >
          已回退到 mock 模式{{
            msg.fallbackReason ? `（${msg.fallbackReason}）` : ''
          }}
        </el-alert>

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
              @click="emit('open-retrieval', msg)"
            >
              检索过程 ({{ msg.retrievedChunks.length }})
            </el-button>
          </div>

          <CitationCapsules
            v-if="msg.citations && msg.citations.length > 0"
            :citations="msg.citations"
            @open="emit('open-citation', $event, msg)"
          />
          <el-alert
            v-if="msg.citations?.some((citation) => citation.support_status && citation.support_status !== 'verified')"
            type="info"
            :closable="false"
            show-icon
            class="citation-support-alert"
          >
            部分资料片段仅与回答相关，自动校验尚未确认其直接支撑关系。
          </el-alert>
          <div v-else class="no-citation">
            本次回答未找到直接资料依据
          </div>

          <FollowUpSuggestions
            v-if="msg.followUpQuestions && msg.followUpQuestions.length > 0"
            :questions="msg.followUpQuestions"
            @select="emit('follow-up', $event)"
          />
        </div>

        <!-- The backend cannot replace an answer in place. The parent keeps
             this answer and confirms before sending a visible new request. -->
        <div
          v-if="msg.role === 'agent' && !msg.pending"
          class="message-actions"
        >
          <el-button text size="small" @click="copyMessage(msg.content)">
            <el-icon><CopyDocument /></el-icon> 复制
          </el-button>
          <el-button
            text
            size="small"
            title="保留当前回答，将原问题作为新问题再次提问"
            aria-label="保留当前回答并再次提问"
            @click="emit('regenerate', msg)"
          >
            <el-icon><Refresh /></el-icon> 再次提问
          </el-button>
        </div>
      </div>
    </div>
  </template>
</template>

<style scoped>
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

.msg-time {
  font-size: 11px;
  color: #c0c4cc;
  margin-top: 4px;
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

.no-citation {
  font-size: 12px;
  color: #909399;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 4px;
}

.fallback-alert {
  margin-top: 6px;
  padding: 4px 10px;
  font-size: 12px;
}

.citation-support-alert {
  margin-top: 6px;
  padding: 4px 10px;
  font-size: 12px;
}

/* Per-message action buttons (copy / regenerate) */
.message-actions {
  display: flex;
  gap: 4px;
  margin-top: 6px;
}

.message-actions .el-button {
  padding: 2px 6px;
  color: #909399;
}

.message-actions .el-button:hover {
  color: #409eff;
}

.message-actions .el-icon {
  margin-right: 2px;
}

/* Markdown rendered AI answers. v-html content is not scoped, so we
   target descendants with :deep(). */
.markdown-body {
  white-space: normal;
  font-size: 14px;
  line-height: 1.7;
}

.markdown-body :deep(p) {
  margin: 0.5em 0;
}

.markdown-body :deep(p:first-child) {
  margin-top: 0;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) {
  margin: 0.8em 0 0.4em;
  font-weight: 600;
  line-height: 1.4;
}

.markdown-body :deep(h1) {
  font-size: 1.4em;
}

.markdown-body :deep(h2) {
  font-size: 1.25em;
}

.markdown-body :deep(h3) {
  font-size: 1.1em;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0.5em 0;
  padding-left: 1.5em;
}

.markdown-body :deep(li) {
  margin: 0.2em 0;
}

.markdown-body :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 0.15em 0.4em;
  border-radius: 3px;
  font-size: 0.9em;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
}

.markdown-body :deep(pre) {
  margin: 0.6em 0;
  padding: 12px;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 6px;
  overflow-x: auto;
}

.markdown-body :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
  font-size: 0.9em;
}

.markdown-body :deep(blockquote) {
  margin: 0.5em 0;
  padding: 0.2em 0.9em;
  border-left: 3px solid #dcdfe6;
  color: #606266;
  background: #fafafa;
}

.markdown-body :deep(a) {
  color: #409eff;
  text-decoration: none;
}

.markdown-body :deep(a:hover) {
  text-decoration: underline;
}

.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 0.6em 0;
  width: 100%;
  font-size: 0.95em;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #dcdfe6;
  padding: 6px 10px;
  text-align: left;
}

.markdown-body :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
}

.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid #dcdfe6;
  margin: 1em 0;
}

.markdown-body :deep(img) {
  max-width: 100%;
}
</style>
