# Bug 排查与项目提升 规格

## Why
当前平台主体功能已实现，但存在 P0/P1 级问题影响演示与验收：前端 page_size=200 与后端 le=100 不一致导致 422；依赖课程 ID 的页面在无数据时请求 undefined 触发 404；仪表盘空白；demo 数据不足以覆盖全部页面；错误提示直接暴露 Pydantic 细节。本规格旨在系统性修复这些问题，使项目达到"可演示、可解释、可提交"状态。

## What Changes

### A. P0 Bug 修复
- 新增 `frontend/src/constants/pagination.ts`，集中定义 `DEFAULT_PAGE_SIZE=20`、`MAX_PAGE_SIZE=100`。
- 替换 5 处 `page_size: 200` 为 `MAX_PAGE_SIZE`（TodosView/QuizView/PlansView/OutlineView/MultiPlanView）。
- 依赖 course_id 的页面增加空状态保护：无课程时不发起 `course/{id}/xxx` 请求。
- 前端错误提示统一：后端 422/404/500 转换为用户可理解文案，不暴露原始 JSON。

### B. 仪表盘重做
- 后端新增 `GET /api/v1/dashboard/summary`，聚合返回：course_count、material_count、knowledge_point_count、todo_today_count、todo_completed_count、agent_run_count。
- 前端 `DashboardView.vue` 重做：欢迎区 + 6 个统计卡片 + 今日待办 + 最近课程 + 最近 Agent 运行 + 快捷入口，全部带 empty 状态。

### C. Demo 数据增强
- `seed_demo_data.py` 补充：≥3 条待办（含今日 1 条、已完成 1 条）、1 个学习目标 + 2 个任务、1 个测验（含题目）、1 条对话 + 1 条带 citation 回答、≥2 条 AgentRun + AgentStep。保持幂等。

### D. Agent 审计页增强
- `AgentRunsView.vue` 列表新增 provider、model 列；详情抽屉检索步骤展示 chunk_id/score/snippet/is_cited（从 output_data 解析）。
- 后端 `agent_runs` list 已支持筛选，无需改动。

### E. 全站错误与空状态统一
- 新增 `frontend/src/utils/error.ts`，`parseApiError(err)` 统一解析：422→"参数不合法，请检查输入"；404→"数据不存在或无权访问"；500→"服务异常，请稍后重试"；网络错误→"网络异常"。
- 各页面列表补 `el-empty` 空状态；生成按钮 loading 禁用；删除操作 ElMessageBox 确认。

## Impact
- 前端：新增 constants/pagination.ts、utils/error.ts、api/dashboard.ts；重写 DashboardView.vue；增强 AgentRunsView.vue；5 个 View 修 page_size；MainLayout 无变化。
- 后端：新增 dashboard endpoint + schema + 测试；seed_demo_data.py 扩展；无破坏性改动。
- 测试：后端新增 test_dashboard.py；前端 npm run build 通过。
- 不引入新依赖，不改动数据库 schema（仅 seed 数据）。
