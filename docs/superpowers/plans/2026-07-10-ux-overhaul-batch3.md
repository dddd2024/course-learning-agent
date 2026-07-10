# UX 第三批改进计划：体验打磨

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复响应式布局、分页缺失、缺少确认弹窗、缺少停止生成等影响用户体验的关键问题

**Architecture:** 前端 Vue 3 + Element Plus，后端 FastAPI + SQLAlchemy + SQLite。改进分三组并行实施：响应式布局、分页+确认弹窗、交互增强。

**Tech Stack:** Vue 3, TypeScript, Element Plus, FastAPI, AbortController

---

## Task 1: 响应式布局 @media 查询

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue`
- Modify: `frontend/src/views/LearnView.vue`
- Modify: `frontend/src/views/KnowledgeGraphView.vue`
- Modify: `frontend/src/views/ChatView.vue`

### MainLayout.vue
- 添加 `@media (max-width: 768px)` 断点
- 小屏幕默认折叠侧边栏（`isCollapse` 初始值改为基于窗口宽度）
- 侧边栏改为 `position: fixed` + overlay 在小屏上

### LearnView.vue
- 添加 `@media (max-width: 1024px)` 断点
- TOC 侧栏在小屏上转为可折叠面板
- AI 助手在小屏上转为底部抽屉

### KnowledgeGraphView.vue
- 添加 `@media (max-width: 1024px)` 断点
- 三栏在小屏上垂直堆叠

### ChatView.vue
- 添加 `@media (max-width: 768px)` 断点
- 对话侧栏在小屏上转为抽屉式

---

## Task 2: LogsView 和 AgentRunsView 分页

**Files:**
- Modify: `frontend/src/views/LogsView.vue`
- Modify: `frontend/src/views/AgentRunsView.vue`

### LogsView.vue
- 添加 `query.page` 和 `query.page_size` 响应式变量
- 添加 `el-pagination` 组件
- 将硬编码 `{ page: 1, page_size: 50 }` 改为使用响应式变量

### AgentRunsView.vue
- 添加 `query.page` 和 `query.page_size` 响应式变量
- 添加 `el-pagination` 组件
- 将硬编码 `{ limit: 50, offset: 0 }` 改为基于页码计算

---

## Task 3: 确认弹窗

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue`
- Modify: `frontend/src/views/KnowledgeGraphView.vue`

### MainLayout.vue
- `handleLogout()` 添加 `ElMessageBox.confirm` 确认

### KnowledgeGraphView.vue
- `handleRebuild()` 添加 `ElMessageBox.confirm` 确认

---

## Task 4: ChatView 停止生成

**Files:**
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/api/chat.ts`

### chat.ts
- `sendMessageStream` 添加 `AbortSignal` 参数支持

### ChatView.vue
- 创建 `AbortController` 实例，传入 `sendMessageStream`
- 添加"停止"按钮，点击调用 `controller.abort()`
- 中断后保留已接收的内容

---

## Task 5: LearnView AI 助手增强

**Files:**
- Modify: `frontend/src/views/LearnView.vue`

- 添加"停止生成"按钮（AbortController 或超时取消）
- 添加"清空对话"按钮，重置 `aiMessages`

---

## Task 6: QuizView 键盘快捷键

**Files:**
- Modify: `frontend/src/views/QuizView.vue`

- 选择题：数字键 1-4 选择选项
- 判断题：Y/T 选择正确，N/F 选择错误
- Enter/Space 提交当前答案
- 添加快捷键提示文字

---

## Task 7: LLM 请求超时 + API 分页参数

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/api/material.ts`
- Modify: `frontend/src/api/knowledge.ts`
- Modify: `frontend/src/api/quiz.ts`

### index.ts
- 全局超时从 15s 改为 30s

### material.ts
- `MaterialListParams` 添加 `page` 和 `page_size` 可选字段

### knowledge.ts
- `listKnowledgePoints` 添加可选 `page` 和 `page_size` 参数

### quiz.ts
- `QuizListResult` 添加 `total` 字段
- `getQuizzes` 添加可选 `page` 和 `page_size` 参数
