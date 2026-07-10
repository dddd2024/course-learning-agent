# UX 全面改进计划

> **目标：** 从"能用"提升到"好用"，全面改善用户体验

**架构：** 前端 Vue 3 + Element Plus + vis-network，后端 FastAPI + SQLAlchemy + SQLite。改进分三个批次：P0 关键修复 → P1 核心体验 → P2 体验打磨。

**技术栈：** Vue 3, TypeScript, Element Plus, FastAPI, SQLAlchemy

---

## 第一批：P0 关键修复（影响核心功能）

### Task 1: 修复 LearnView 硬编码值，使其适用于所有课程

**问题：**
- 硬编码图片 URL `http://127.0.0.1:8000/uploads/`
- 硬编码 KEY_TERMS（计算机网络专用术语 TCP/UDP/IP/MAC 等）
- 硬编码 USELESS_PATTERNS / NOISE_LINE_PATTERNS（特定教材引用）

**Files:**
- Modify: `frontend/src/views/LearnView.vue`
- Modify: `frontend/src/config/runtime.ts` (新建)

- [ ] **Step 1: 创建运行时配置文件**

创建 `frontend/src/config/runtime.ts`，从环境变量或 API 获取后端地址：

```typescript
// 自动检测后端地址：优先用 Vite 代理的同源地址
const BACKEND_BASE = import.meta.env.VITE_API_BASE || ''
export const UPLOAD_BASE = BACKEND_BASE || window.location.origin
```

- [ ] **Step 2: 替换硬编码图片 URL**

在 LearnView.vue 中，将 `http://127.0.0.1:8000/uploads/` 替换为从 API 配置动态获取。

- [ ] **Step 3: 将 KEY_TERMS 改为动态生成**

从当前课程的知识点标题中提取术语，而非硬编码。在 loadChunks 后从知识点 API 获取关键词列表。

- [ ] **Step 4: 将 USELESS_PATTERNS 改为通用规则**

移除特定教材引用（Forouzan、Tanenbaum 等），保留通用噪声模式（纯数字行、纯标点行、页码行等）。

- [ ] **Step 5: 验证不同课程的显示效果**

### Task 2: 修复 CourseDetailView 缺少"学习"入口

**问题：** `/courses/:id/learn` 路由存在但 CourseDetailView 只有 3 个入口卡片（资料/问答/知识点），用户无法从正常导航到达学习页面。

**Files:**
- Modify: `frontend/src/views/CourseDetailView.vue`

- [ ] **Step 1: 添加"学习"入口卡片**

在 3 个入口卡片后添加第 4 个"文档学习"入口，链接到 `/courses/:id/learn`。

- [ ] **Step 2: 为每个入口卡片添加数量统计**

调用 API 获取资料数、知识点数、对话数并显示在卡片上。

### Task 3: 修复 OutlineView goToChat 函数命名与行为不符

**问题：** `goToChat()` 函数实际跳转到 `/learn` 而非 `/chat`。

**Files:**
- Modify: `frontend/src/views/OutlineView.vue`

- [ ] **Step 1: 重命名函数为 goToLearn**

将 `goToChat` 重命名为 `goToLearn`，确保函数名与行为一致。

### Task 4: 修复对话列表 N+1 查询和缺失功能

**问题：**
- 后端 `list_messages` 每条消息单独查询 citations（N+1）
- 对话不可删除/重命名
- 对话列表无搜索

**Files:**
- Modify: `backend/app/api/v1/endpoints/conversations.py`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/api/chat.ts`

- [ ] **Step 1: 后端修复 N+1 查询**

在 `list_messages` 中使用 `selectinload(Message.citations)` 一次性加载。

- [ ] **Step 2: 后端添加对话删除端点**

```python
@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, ...):
    ...
```

- [ ] **Step 3: 后端添加对话重命名端点**

```python
@router.patch("/{conversation_id}")
def rename_conversation(conversation_id: int, title: str, ...):
    ...
```

- [ ] **Step 4: 前端添加删除和重命名 UI**

在对话列表项添加右键菜单或操作按钮，支持删除（带确认）和重命名（弹窗输入）。

---

## 第二批：P1 核心体验改进

### Task 5: AI 回答 Markdown 渲染

**问题：** ChatView 和 LearnView 的 AI 回答使用 `white-space: pre-wrap` 或简单 `\n→<br>` 替换，不渲染 Markdown 格式（标题、列表、代码块、加粗等）。

**Files:**
- Modify: `frontend/package.json` (添加 marked + DOMPurify)
- Modify: `frontend/src/components/chat/MessageList.vue`
- Modify: `frontend/src/views/LearnView.vue`
- Create: `frontend/src/utils/markdown.ts`

- [ ] **Step 1: 安装依赖**

```bash
cd frontend && npm install marked dompurify
```

- [ ] **Step 2: 创建 markdown 渲染工具**

```typescript
import { marked } from 'marked'
import DOMPurify from 'dompurify'

export function renderMarkdown(text: string): string {
  const html = marked.parse(text, { breaks: true, gfm: true })
  return DOMPurify.sanitize(html)
}
```

- [ ] **Step 3: 在 MessageList.vue 中替换 pre-wrap 为 Markdown 渲染**

- [ ] **Step 4: 在 LearnView.vue 中替换 renderAnswer 为 Markdown 渲染**

### Task 6: 消息复制按钮和重新生成

**Files:**
- Modify: `frontend/src/components/chat/MessageList.vue`
- Modify: `frontend/src/views/ChatView.vue`

- [ ] **Step 1: 添加复制按钮**

在每条 AI 消息底部添加复制按钮，使用 `navigator.clipboard.writeText`。

- [ ] **Step 2: 添加重新生成按钮**

在 AI 消息底部添加重新生成按钮，重新发送上一条用户消息。

### Task 7: 全局空状态组件

**问题：** 多个页面在无数据时显示空白或不友好的提示。

**Files:**
- Create: `frontend/src/components/common/EmptyState.vue`

- [ ] **Step 1: 创建通用空状态组件**

```vue
<template>
  <div class="empty-state">
    <el-icon :size="60" :class="icon"><component :is="icon" /></el-icon>
    <h3>{{ title }}</h3>
    <p v-if="description">{{ description }}</p>
    <el-button v-if="actionText" type="primary" @click="$emit('action')">
      {{ actionText }}
    </el-button>
  </div>
</template>
```

- [ ] **Step 2: 在所有列表页面使用空状态组件**

替换 CoursesView、MaterialsView、ChatView、OutlineView、QuizView、TodosView 等的空数据展示。

### Task 8: 添加面包屑导航

**问题：** 课程子页面路径深达 3 级，无面包屑，用户无法了解当前位置。

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue`
- Create: `frontend/src/components/common/Breadcrumbs.vue`

- [ ] **Step 1: 创建面包屑组件**

根据当前路由自动生成面包屑：首页 > 课程 > 课程名 > 子页面。

- [ ] **Step 2: 在 MainLayout 中集成面包屑**

在顶栏下方添加面包屑区域。

### Task 9: 对话列表搜索和分页

**Files:**
- Modify: `backend/app/api/v1/endpoints/conversations.py`
- Modify: `frontend/src/views/ChatView.vue`

- [ ] **Step 1: 后端添加分页参数**

- [ ] **Step 2: 前端添加搜索框和分页控件**

### Task 10: 测验体验改进

**问题：**
- 结果不显示正确答案
- 无答题进度指示
- 退出无确认
- 测验不可删除

**Files:**
- Modify: `frontend/src/views/QuizView.vue`
- Modify: `backend/app/api/v1/endpoints/quizzes.py`

- [ ] **Step 1: 结果页显示正确答案**
- [ ] **Step 2: 添加答题进度条**
- [ ] **Step 3: 退出确认**
- [ ] **Step 4: 测验删除功能**

---

## 第三批：P2 体验打磨

### Task 11: 列表分页统一

**问题：** materials, knowledge-points, quizzes, todos 等端点无分页。

**Files:**
- Modify: 多个后端端点
- Modify: 多个前端页面

### Task 12: 响应式布局基础

**问题：** 无 @media 查询，平板/手机完全不可用。

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue`
- Modify: 多个视图组件

- [ ] **Step 1: 侧边栏可折叠**
- [ ] **Step 2: 三栏布局在小屏幕上转为单栏**

### Task 13: 顶栏动态标题

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue`

### Task 14: 截止日期禁用过去日期

**Files:**
- Modify: `frontend/src/views/PlansView.vue`
- Modify: `frontend/src/views/MultiPlanView.vue`

### Task 15: 滚动到底部按钮（聊天）

**Files:**
- Modify: `frontend/src/views/ChatView.vue`
