# Phase 2 工程改进与 Bug 修复计划

> 基于 `课程学习助手下一步Bug修复与工程改进计划.docx` (基线提交 81b9bc5)

**目标:** 仅做现有功能缺陷修复与工程质量改进，不引入新业务能力。修复重新解析失败后的旧结果可见性、清理主观指标 UI 残留、清理无关目录、修复 CI 触发、ChatView 工程拆分与测试补强。

**架构:** 后端 parse 端点保留旧 chunks；前端清理相关度/置信度 UI 并改进状态展示；CI 增加 workflow_dispatch；ChatView 拆分为展示组件。

**技术栈:** FastAPI / SQLAlchemy / Vue 3 / Element Plus / pytest / GitHub Actions

---

## 执行边界

- 只覆盖现有功能缺陷修复与工程质量改进
- 不引入新业务能力、新页面、新模型能力或新业务闭环
- 每个 commit 保持可运行
- 暂缓事项：资料解析版本管理、句级 citation quote_start/quote_end、薄弱点学习闭环、一键演示、知识点大纲联动、大规模 Alembic 迁移

## 任务分解

### Task 1 (P0): 重新解析失败后保留旧结果可见性 - 后端
- **文件:** `backend/app/api/v1/endpoints/parse.py`, `backend/app/tests/test_parse.py`
- **问题:** 重新解析失败时，无论是否有旧 chunks 都设为 failed，导致上一版可用结果丢失
- **修复:** 解析前记录 `existing_chunk_count`；失败时若旧 chunks 存在则保持 `status="ready"` 并写入 `error_message`，否则才设为 `failed`
- **测试:** 旧 chunks 存在时解析失败 → status 保持 ready + error_message 含提示；无旧 chunks 时解析失败 → status=failed

### Task 2 (P0): 重新解析失败后保留旧结果可见性 - 前端
- **文件:** `frontend/src/views/MaterialsView.vue`
- **问题:** status==ready 且 error_message 非空时未提示"上次解析失败"
- **修复:** 状态标签显示"已就绪（上次解析失败）"+ tooltip 展示错误；"查看片段"按钮保持可用；概览弹窗顶部显示轻量提示
- **依赖:** Task 1 后端字段已就绪

### Task 3 (P1): 移除主观指标 UI 残留
- **文件:** `frontend/src/views/ChatView.vue`, `frontend/src/views/MaterialsView.vue`
- **问题:** ChatView 引用胶囊 title 含"相关度 xx%"和 confidencePercent 函数；MaterialsView 检索结果展示"相关度 xx%"
- **修复:** ChatView 删除 confidencePercent 函数，胶囊 title 改为"点击查看原文证据"；MaterialsView 删除检索结果的"相关度"标签

### Task 4 (P1): 清理无关目录与 CI 触发修复
- **文件:** `algorithmic-art/` (删除), `.github/workflows/ci.yml`
- **问题:** algorithmic-art 与主线无关污染仓库；CI 缺少 workflow_dispatch 手动触发
- **修复:** `git rm -r algorithmic-art`；CI 增加 `workflow_dispatch:` 触发器

### Task 5 (P2): ChatView 工程拆分
- **文件:** `frontend/src/views/ChatView.vue`, 新建 `frontend/src/components/chat/` 下展示组件
- **问题:** ChatView 承担消息列表、SSE 状态栏、引用胶囊、证据抽屉、检索命中、追问建议过多职责
- **修复:** 无行为改变地抽取展示组件（MessageList、SseStatusPanel、CitationCapsules、EvidenceDrawer、RetrievalDrawer、FollowUpSuggestions）；不抽 composable；不改 API 调用时序
- **验收:** npm run build 通过 + 手工验证提问、引用抽屉、SSE 状态栏、追问建议

### Task 6 (P2): 测试补强与验收脚本
- **文件:** `backend/app/tests/test_parse.py`, `scripts/verify_phase2_engineering.ps1`
- **问题:** 需固化"无主观指标 UI"和"重新解析失败旧结果可见"为测试/脚本
- **修复:** 补强 parse 测试；新增验收脚本（pytest + npm build + grep 主观指标残留检查）

### Task 7: 验收与上传
- 后端全量 pytest 通过
- 前端 npm run build 通过
- agent-browser 验证关键页面
- web-design-guidelines 复核前端
- git commit + push 到 GitHub

## 执行顺序与提交策略

1. Task 1 (P0 后端) → commit
2. Task 2 (P0 前端) → commit
3. Task 3 (P1 主观指标) → commit
4. Task 4 (P1 清理 + CI) → commit
5. 审计：pytest + npm build + grep 检查
6. Task 5 (P2 ChatView 拆分) → commit
7. Task 6 (P2 测试补强) → commit
8. Task 7 验收 + 上传
