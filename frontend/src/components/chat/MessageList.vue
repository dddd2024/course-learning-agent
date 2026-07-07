<script setup lang="ts">
// Display-only message list. Renders user/agent bubbles, citation
// capsules, retrieval buttons and follow-up suggestions. All actions
// are forwarded to the parent via events.
import {
  ChatDotRound,
  Document,
  Loading,
  User,
} from '@element-plus/icons-vue'
import type { Citation } from '../../api/chat'
import type { ChatMessage } from './types'
import CitationCapsules from './CitationCapsules.vue'
import FollowUpSuggestions from './FollowUpSuggestions.vue'

defineProps<{
  messages: ChatMessage[]
}>()

const emit = defineEmits<{
  (e: 'open-citation', citation: Citation, message: ChatMessage): void
  (e: 'open-retrieval', message: ChatMessage): void
  (e: 'follow-up', question: string): void
}>()
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
          <template v-else>{{ msg.content }}</template>
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
          <div v-else class="no-citation">
            本次回答未找到直接资料依据
          </div>

          <FollowUpSuggestions
            v-if="msg.followUpQuestions && msg.followUpQuestions.length > 0"
            :questions="msg.followUpQuestions"
            @select="emit('follow-up', $event)"
          />
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
</style>
