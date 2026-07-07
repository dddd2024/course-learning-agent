# Phase 2 体验重构 任务清单

> 按 TDD（先写失败测试，再写最小实现）执行。每个模块完成后运行相关测试。

- [ ] Task A: 胶囊式引用与原文高亮追溯
  - [ ] A.1: 后端新增 `GET /api/v1/chunks/{chunk_id}` + 权限校验 + test_chunks.py（owner 可访问、cross-user 404、不存在 404）
  - [ ] A.2: CitationResponse 新增 display_label 字段，citations.py 组装
  - [ ] A.3: 前端新增 HighlightedText 工具（escape → 标记 quote_text）
  - [ ] A.4: 前端新增 CitationCapsule 组件（低饱和一行胶囊）
  - [ ] A.5: 前端新增 CitationDrawer 组件（原文 + 高亮）
  - [ ] A.6: ChatView 替换大块引用卡片为胶囊，同 chunk 去重
  - [ ] A.7: npm run build 验证

- [ ] Task B: 可折叠实时 Agent 执行状态（SSE）
  - [ ] B.1: 后端抽离 chat_service.run_chat() 共用逻辑
  - [ ] B.2: 后端新增 `POST /api/v1/chat/stream` SSE endpoint + test_chat_stream.py
  - [ ] B.3: 后端新增 AGENT_TRACE_MODE 配置（默认 error）
  - [ ] B.4: 前端 ChatView 接入 SSE 流式，实时状态折叠栏
  - [ ] B.5: 状态栏默认折叠、发送中展开、完成折叠、失败展开+建议
  - [ ] B.6: npm run build 验证

- [ ] Task C: 资料解析概览与客观异常提示
  - [ ] C.1: 后端新增 `GET /api/v1/materials/{id}/overview` + test_material_overview.py（chunk_count/page_range/keywords/warnings + 权限）
  - [ ] C.2: 前端 CourseDetailView/MaterialsView 新增资料概览区
  - [ ] C.3: npm run build 验证

- [ ] Task D: 上传资料安全扫描
  - [ ] D.1: 后端新增 MaterialSecurityFinding 模型
  - [ ] D.2: 后端解析流程加入规则扫描 + test_security_scan.py
  - [ ] D.3: overview 响应包含 security_findings_count
  - [ ] D.4: course_qa prompt 加入防护语句
  - [ ] D.5: 前端资料详情页显示可疑片段
  - [ ] D.6: npm run build 验证

- [ ] Task E: 错误日志工程化
  - [ ] E.1: 后端新增 AgentErrorLog 模型
  - [ ] E.2: chat/stream 失败时写入 agent_error_logs
  - [ ] E.3: 后端新增 `GET /api/v1/agent-error-logs` + test_error_logs.py
  - [ ] E.4: npm run build 验证

- [ ] Task F: Demo 数据与验收
  - [ ] F.1: seed 脚本补充可演示引用/风险资料数据
  - [ ] F.2: 后端全量 pytest 通过（含新增测试，不回归）
  - [ ] F.3: 前端 npm run build 通过
  - [ ] F.4: agent-browser 验证核心流程
  - [ ] F.5: git-commit 提交并推送到 GitHub

# Task Dependencies
- Task A 后端 chunks endpoint 是 CitationDrawer 的依赖
- Task B 依赖 Task A（胶囊引用在 stream final 事件中返回）
- Task C 独立，可与 A/B 并行
- Task D 依赖 Task C（overview 包含 security_findings_count）
- Task E 依赖 Task B（stream 失败时写日志）
- Task F 依赖全部完成
