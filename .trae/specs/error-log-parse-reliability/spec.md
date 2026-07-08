# 异常日志与资料解析可靠性改造 实施计划

> 来源：`课程学习助手_异常日志与资料解析可靠性改造计划.docx`
> 仓库：dddd2024/course-learning-agent
> 分支：main

## 背景

实测暴露五个问题（P1-P5）：
- P1：上传时间差 8 小时（后端 UTC naive + 前端 toLocaleString）。
- P2：解析失败只失败一次，不自动重试，用户不知原因。
- P3：资料长时间卡在 processing，重新处理/查看/删除全禁用，无恢复入口。
- P4：刷新按钮"看起来无效"（数据库仍是 processing，界面不变）。
- P5：日志入口只做 Agent 审计，不覆盖上传/解析/系统错误。

本轮目标：建立"异常可见、原因可查、状态可恢复"的闭环，不做操作流水账。

## 目标

1. **时间统一**：后端统一 timezone-aware UTC；前端统一 `formatLocalDateTime`，全站时间显示一致。
2. **异常日志中心后端**：新增通用 `ErrorLog` 表（只记失败/告警，不记成功），支持 category/level/status/关键词过滤 + 详情 + resolve；按 user 隔离。
3. **解析重试与超时恢复**：Material 增加解析任务字段；parse 接口有限重试（最多 3 次）；list_materials 返回前检查 processing 超时（>300s 转 failed 并写日志）。
4. **前端日志中心**：新增 LogsView；菜单"Agent 审计"改为"日志中心"；资料页 failed/processing 超时行增加"查看原因"与恢复入口。

## 非目标

- 不引入 Celery/Redis/消息队列。
- 不重写 RAG/问答/知识点/计划主流程。
- 不记录所有普通成功操作。
- 不展开最终报告正文。

## 设计决策

- **ErrorLog 与现有 AgentErrorLog 并存**：现有 `agent_error_logs` 表/接口（Phase 2 Task E）只覆盖 agent 步骤且字段固定。本轮新增通用 `error_logs` 表（category=upload/parse/agent/search/system），不破坏现有 agent 审计能力。新接口挂在 `/logs` 前缀。
- **时间**：新增 `app.core.timezone.utc_now()` 返回 timezone-aware UTC；`Material.uploaded_at` 改用该函数；TimestampMixin 已是 `DateTime(timezone=True)`，无需改。`init_db` 增加 `ensure_material_parse_columns` 迁移。
- **解析重试**：抽出 `MaterialParserService.parse_once`；parse endpoint 调用 service 做最多 3 次尝试；每次失败写 error_logs；首次失败无旧片段→failed，重新解析失败有旧片段→保留 ready+warning。
- **超时检测**：`list_materials` 与 parse 前置检查 processing 且 `parse_started_at` 距今 >300s → 转 failed + 写日志。复用现有轮询：刷新后状态会变。
- **前端**：新增 `utils/datetime.ts` 的 `formatLocalDateTime`；MaterialsView 替换散落 `new Date().toLocaleString()`；processing 行显示已耗时；failed/超时行显示"查看原因"。

## 任务分解

### Task A：时间统一

文件：
- 新建：`backend/app/core/timezone.py`（`utc_now()`）
- 修改：`backend/app/models/material.py`（`uploaded_at` 用 `utc_now`）
- 新建：`frontend/src/utils/datetime.ts`（`formatLocalDateTime`）
- 修改：`frontend/src/views/MaterialsView.vue`（替换时间格式化）

### Task B：ErrorLog 模型 + schema + service + endpoints（TDD）

文件：
- 新建：`backend/app/models/general_error_log.py`（`ErrorLog`，避免与现有 `error_log.py` 的 `AgentErrorLog` 冲突）
- 新建：`backend/app/schemas/general_error_log.py`
- 新建：`backend/app/services/error_logger.py`（`log_error(...)` 写入函数）
- 新建：`backend/app/api/v1/endpoints/general_error_logs.py`（GET /logs, GET /logs/{id}, POST /logs/{id}/resolve）
- 修改：`backend/app/api/v1/api.py`（注册 `/logs` 路由）
- 修改：`backend/app/models/__init__.py`（导出 ErrorLog）
- 测试：`backend/app/tests/test_general_error_logs.py`

字段：id, user_id, category(upload/parse/agent/search/system), level(warning/error), status(open/resolved/ignored), title, message, technical_detail, course_id, material_id, agent_run_id, request_path, retry_count, max_retries, created_at, updated_at。

### Task C：Material 解析重试 + 超时恢复（TDD）

文件：
- 修改：`backend/app/models/material.py`（加 parse_started_at/parse_finished_at/parse_attempts/last_parse_error）
- 新建：`backend/app/services/material_parser.py`（`MaterialParserService.parse_once` + 重试）
- 修改：`backend/app/api/v1/endpoints/parse.py`（调用 service；失败写日志）
- 修改：`backend/app/api/v1/endpoints/materials.py`（list_materials 前置超时检测）
- 修改：`backend/app/db/migrations.py`（`ensure_material_parse_columns`）
- 修改：`scripts/init_db.py`（调用新迁移）
- 测试：`backend/app/tests/test_parse.py`（重试/超时/旧片段保留）

### Task D：前端日志中心 + 资料页恢复 UX

文件：
- 新建：`frontend/src/api/logs.ts`
- 新建：`frontend/src/views/LogsView.vue`
- 修改：`frontend/src/layouts/MainLayout.vue`（菜单"Agent 审计"→"日志中心"，指向 /logs）
- 修改：`frontend/src/router/index.ts`（/logs 路由）
- 修改：`frontend/src/views/MaterialsView.vue`（processing 显示已耗时；failed/超时"查看原因"；刷新提示）

## 验收

```powershell
cd backend; python -m pytest app/tests/ -q
cd ../frontend; npm run build
cd ..; pwsh .\scripts\verify_phase2_engineering.ps1
```

- 上传时间与本地时间一致（不再差 8 小时）。
- 解析失败自动重试，达上限后 failed + 写日志。
- processing 超 300s 后刷新列表自动转 failed + 写日志。
- 日志中心只显示异常，按 category 筛选。
- 资料失败行可"查看原因"。
