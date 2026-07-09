# 学习文档页面改进 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将学习文档页面从"原始chunk堆砌"改造为"高效学习界面"，过滤无用内容，增加AI学习指南、目录导航和阅读进度。

**Architecture:** 纯前端改造（LearnView.vue），利用现有 chat API 生成学习指南。后端不需要改动——chunk 数据已包含 title 和 page_no，前端做智能过滤和展示优化即可。

**Tech Stack:** Vue 3 + Element Plus + TypeScript，现有 `sendMessage` chat API

---

## File Structure

- Modify: `frontend/src/views/LearnView.vue` — 核心改造文件
- Modify: `frontend/src/api/material.ts` — Chunk 类型补充 score 字段（可选）
- No backend changes needed

---

### Task 1: 过滤无用 chunk

**Files:**
- Modify: `frontend/src/views/LearnView.vue`

**问题**：当前直接渲染所有 chunk，包括封面页（"第五章 数据链路层"、课程名、学院名）、目录页、页眉页脚等对学生学习无价值的内容。

**方案**：在前端 `loadChunks` 后添加 `filterUsefulChunks` 函数，过滤规则：
- 文本去空格后 < 40 字符的 chunk（封面页、页码标注）
- 文本只包含课程名/学院名/日期/教师名等元信息的 chunk
- 文本以"第X页"或纯数字开头的 chunk（页眉）
- chunk 的 title 等于文本内容的 chunk（纯标题无正文）

- [ ] **Step 1: 添加过滤函数**

在 LearnView.vue 的 script 中添加：

```typescript
const USELESS_PATTERNS = [
  /^第[一二三四五六七八九十\d]+章\s*$/,  // 纯章节标题
  /^网络空间安全学院/,
  /^计算机(?:网络|操作系统|数据结构|数据库)\s*$/,
  /^\d{4}年\d*月?\s*$/,
  /^[主讲教师|教师][:：]/,
]

function isUsefulChunk(chunk: Chunk): boolean {
  const text = chunk.text.trim()
  if (text.length < 40) return false
  for (const pattern of USELESS_PATTERNS) {
    if (pattern.test(text)) return false
  }
  // 标题和正文完全相同说明只有标题没有内容
  if (chunk.title && chunk.title.trim() === text) return false
  return true
}

function filterUsefulChunks(rawChunks: Chunk[]): Chunk[] {
  return rawChunks.filter(isUsefulChunk)
}
```

- [ ] **Step 2: 在 loadChunks 中调用过滤**

```typescript
async function loadChunks() {
  // ... existing fetch code ...
  chunks.value = filterUsefulChunks(data.items)
}
```

- [ ] **Step 3: 添加过滤提示**

在文档区域顶部显示"已过滤 X 个无关片段（封面/目录等）"：

```html
<div v-if="filteredCount > 0" class="filter-hint">
  <el-tag type="info" size="small">
    已自动过滤 {{ filteredCount }} 个无关片段（封面/目录/页眉等）
  </el-tag>
</div>
```

---

### Task 2: AI 学习指南模式

**Files:**
- Modify: `frontend/src/views/LearnView.vue`

**问题**：学生看到的是原始分块文本，缺乏结构化的学习指引。

**方案**：添加"学习指南"按钮，点击后调用 chat API 将当前资料的 chunks 发给 AI，生成结构化学习摘要（包含核心概念、重点难点、学习建议）。结果以卡片形式展示在文档上方。

- [ ] **Step 1: 添加状态和生成函数**

```typescript
const studyGuide = ref('')
const studyGuideLoading = ref(false)

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
```

- [ ] **Step 2: 添加学习指南 UI**

在文档内容区域上方添加可折叠的学习指南卡片：

```html
<div v-if="studyGuide || studyGuideLoading" class="study-guide-card">
  <div class="study-guide-head">
    <el-icon color="#409eff"><MagicStick /></el-icon>
    <span>AI 学习指南</span>
    <el-button text size="small" @click="studyGuide = ''">关闭</el-button>
  </div>
  <div v-loading="studyGuideLoading" class="study-guide-body">
    <div v-html="renderAnswer(studyGuide)"></div>
  </div>
</div>
```

- [ ] **Step 3: 在 header 添加生成按钮**

```html
<el-button
  type="primary"
  plain
  size="small"
  :loading="studyGuideLoading"
  @click="generateStudyGuide"
  :disabled="chunks.length === 0"
>
  <el-icon><MagicStick /></el-icon>
  生成学习指南
</el-button>
```

---

### Task 3: 左侧目录导航 + 阅读进度条

**Files:**
- Modify: `frontend/src/views/LearnView.vue`

**问题**：学生无法快速跳转到感兴趣的章节，也不知道自己读了多少。

**方案**：
- 在文档阅读区左侧添加一个窄边栏，显示各 chunk 的标题作为目录，点击跳转
- 顶部添加阅读进度条，随滚动更新

- [ ] **Step 1: 添加目录导航**

```html
<div class="doc-toc">
  <div class="toc-label">目录</div>
  <div
    v-for="(chunk, idx) in chunks"
    :key="chunk.id"
    class="toc-item"
    :class="{ active: activeChunkIndex === idx }"
    @click="scrollToChunk(idx)"
  >
    <span class="toc-num">{{ idx + 1 }}</span>
    <span class="toc-title">{{ chunk.title || `第${chunk.page_no}页` }}</span>
  </div>
</div>
```

- [ ] **Step 2: 添加滚动监听和跳转**

```typescript
const activeChunkIndex = ref(0)
const readProgress = ref(0)

function scrollToChunk(idx: number) {
  const el = document.getElementById(`chunk-${chunks.value[idx].id}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function handleDocScroll() {
  const reader = document.querySelector('.doc-reader')
  if (!reader) return
  const scrollTop = reader.scrollTop
  const scrollHeight = reader.scrollHeight - reader.clientHeight
  readProgress.value = scrollHeight > 0 ? Math.round((scrollTop / scrollHeight) * 100) : 0

  // Find which chunk is currently in view
  for (let i = chunks.value.length - 1; i >= 0; i--) {
    const el = document.getElementById(`chunk-${chunks.value[i].id}`)
    if (el && el.offsetTop - reader.offsetTop <= scrollTop + 50) {
      activeChunkIndex.value = i
      break
    }
  }
}
```

在 `.doc-reader` 上添加 `@scroll="handleDocScroll"`。

- [ ] **Step 3: 添加进度条**

```html
<el-progress
  :percentage="readProgress"
  :show-text="false"
  :stroke-width="3"
  class="read-progress"
/>
```

---

### Task 4: 改进内容展示

**Files:**
- Modify: `frontend/src/views/LearnView.vue`

**问题**：当前文本展示是纯 `white-space: pre-wrap`，缺乏段落分隔、术语高亮和视觉层次。

**方案**：
- 改进 chunk 卡片样式：更好的间距、阴影、标题区分
- 自动高亮常见网络术语（数据链路层、TCP、路由器等）
- 添加 chunk 类型标识（正文 vs 标题 vs 示例）

- [ ] **Step 1: 改进卡片样式**

调整 `.doc-chunk` 样式，增加左侧色条标识、更好的阴影和间距。

- [ ] **Step 2: 添加术语高亮**

```typescript
const KEY_TERMS = [
  '数据链路层', '物理层', '网络层', '传输层', '应用层',
  'TCP', 'UDP', 'IP', 'MAC地址', '路由器', '交换机', '网桥',
  '帧', '分组', '比特', '带宽', '吞吐量', '时延',
  'PPP', 'HDLC', 'CSMA/CD', 'VLAN', 'ARP',
  'OSI', '封装', '解封装', '复用', '分用',
]

function highlightTerms(text: string): string {
  const escapeHtml = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  let result = escapeHtml(text)
  for (const term of KEY_TERMS) {
    const regex = new RegExp(`(?<!<[^>]*)${term}`, 'g')
    result = result.replace(regex, `<span class="term-highlight">${term}</span>`)
  }
  return result
}
```

- [ ] **Step 3: 用 v-html 渲染高亮后的文本**

将 `.doc-chunk-text` 改为 `v-html="highlightTerms(chunk.text)"`。

---

### Task 5: 构建测试 + agent-browser 验证

- [ ] **Step 1: 构建前端**

```bash
cd f:\course-learning-agent\frontend && npm run build
```

- [ ] **Step 2: 用 agent-browser 验证**

打开学习页面，截图检查：
1. 封面页等无用内容是否被过滤
2. 目录导航是否可用
3. 学习指南按钮是否可点击生成
4. 术语高亮是否显示
5. 进度条是否随滚动更新

- [ ] **Step 3: 提交**

```bash
git add -A && git commit -m "feat: improve learn view with content filtering, study guide, TOC navigation"
```
