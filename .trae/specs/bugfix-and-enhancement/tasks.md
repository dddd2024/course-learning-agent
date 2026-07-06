# Bug 排查与项目提升 任务清单

> 按 TDD（先写失败测试，再写最小实现）执行。每个模块完成后运行相关测试。

- [x] Task A: P0 Bug 修复（page_size + 空状态 + 错误提示）
  - [x] A.1: 新增 frontend/src/constants/pagination.ts（DEFAULT_PAGE_SIZE=20, MAX_PAGE_SIZE=100）
  - [x] A.2: 替换 5 处 page_size: 200 → MAX_PAGE_SIZE（TodosView/QuizView/PlansView/OutlineView/MultiPlanView）
  - [x] A.3: 新增 frontend/src/utils/error.ts（parseApiError 统一错误文案）
  - [x] A.4: 依赖 course_id 的页面增加空状态保护（无课程时不请求子资源）
  - [x] A.5: npm run build 验证通过

- [x] Task B: 仪表盘重做
  - [x] B.1: 编写 backend test_dashboard.py 失败测试（summary 返回 6 项聚合计数 + user 隔离）
  - [x] B.2: 实现 GET /api/v1/dashboard/summary（聚合 courses/materials/knowledge_points/todos/agent_runs）
  - [x] B.3: 新增 frontend/src/api/dashboard.ts 封装
  - [x] B.4: 重写 DashboardView.vue（欢迎区 + 6 卡片 + 今日待办 + 最近课程 + 最近 Agent 运行 + 快捷入口 + empty）
  - [x] B.5: pytest + npm run build 验证通过

- [x] Task C: Demo 数据增强
  - [x] C.1: 扩展 seed_demo_data.py（todo/plan/quiz/conversation/agent_run，幂等）
  - [x] C.2: 运行 seed 脚本验证不报错
  - [x] C.3: 现有测试不回归

- [x] Task D: Agent 审计页增强
  - [x] D.1: AgentRunsView.vue 列表新增 provider、model 列
  - [x] D.2: 详情抽屉检索步骤展示 chunk_id/score/snippet/is_cited
  - [x] D.3: npm run build 验证通过

- [x] Task E: 全站错误与空状态统一
  - [x] E.1: 各列表页应用 parseApiError 替换原始错误展示
  - [x] E.2: 生成按钮 loading 禁用 + 删除操作确认弹窗
  - [x] E.3: npm run build 验证通过

- [x] Task F: 验收与提交
  - [x] F.1: 后端全量 pytest 通过（165 passed）
  - [x] F.2: 前端 npm run build 通过
  - [x] F.3: agent-browser 验证核心页面无红色错误（dashboard/courses/todos/plans/quizzes/agent-runs/profile 全部加载无 4xx/5xx）
  - [x] F.4: git-commit 提交并推送到 GitHub

# Task Dependencies
- Task B 后端依赖 Task A 完成（避免 page_size 问题干扰）
- Task C 独立，可与 B/D/E 并行
- Task D、E 依赖 Task A（error.ts、pagination 常量）
- Task F 依赖全部完成
