<template>
  <div class="learn-page">
    <!-- Header -->
    <div class="learn-header">
      <el-button link @click="goBack">
        <el-icon><ArrowLeft /></el-icon>
        返回课程
      </el-button>
      <span class="learn-title">{{ courseName || '课程学习' }}</span>
      <el-select
        v-model="selectedMaterialId"
        placeholder="选择学习资料"
        style="width: 260px"
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

    <!-- Main content: document reader + AI assistant -->
    <div class="learn-body">
      <!-- Left: Document reader -->
      <div class="doc-reader">
        <div v-if="docLoading" class="doc-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
          加载资料中...
        </div>
        <div v-else-if="chunks.length === 0" class="doc-empty">
          <el-empty description="请选择一份资料开始学习" :image-size="100" />
        </div>
        <div v-else class="doc-content" @mouseup="handleSelection">
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
            <div class="doc-chunk-text">{{ chunk.text }}</div>
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
import { ArrowLeft, ChatDotRound, InfoFilled, Loading } from '@element-plus/icons-vue'
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
const chunks = ref<Chunk[]>([])
const docLoading = ref(false)

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

async function ensureConversation() {
  if (conversationId.value) return conversationId.value
  const { data } = await createConversation({
    course_id: courseId.value,
    title: '学习助手对话',
  })
  conversationId.value = data.id
  return conversationId.value
}

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
      selectedMaterialId.value = materials.value[0].id
      await loadChunks()
    }
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取资料列表失败'))
  }
})

async function loadChunks() {
  if (!selectedMaterialId.value) return
  docLoading.value = true
  chunks.value = []
  try {
    const { data } = await getChunks(selectedMaterialId.value, { page: 1, page_size: 100 })
    chunks.value = data.items
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

.learn-body {
  display: flex;
  flex: 1;
  overflow: hidden;
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

.doc-chunk {
  margin-bottom: 24px;
  padding: 16px 20px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #ebeef5;
}

.doc-chunk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
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

/* AI Assistant */
.ai-assistant {
  width: 400px;
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
