# Phase 2 回归修复计划

> 基于 `课程学习助手Phase2新Bug修复计划.docx` (审计基线 b10b516 → 5d720b9)

**目标:** 修复 Phase 2 引入的 P0/P1 回归 bug，恢复功能一致性与可演示性。

**架构:** 后端修复 chat_service 失败收尾 + citation 去重 + parse rollback；前端接通 chunk 原文高亮 + SSE fallback 防重复 + 移除主观等级 UI。

**技术栈:** FastAPI / SQLAlchemy / Vue 3 / Element Plus / pytest

---

## 任务分解

### Task 1 (P0-1): 修复失败流程 AgentRun 无法收尾
- **文件:** `backend/app/services/chat_service.py`, `backend/app/tests/test_chat_stream.py`
- **问题:** `_safe_finish_run` 传入 `started_at` 但 `finish_run` 不接受；失败时 run 停留 running
- **修复:** 删除 `started_at`，改传 `duration_ms=int((time.monotonic() - run_started_at) * 1000)`
- **测试:** retrieve 失败 / generate 失败 / sync /chat 失败 三条路径

### Task 2 (P1-1): Citation 去重
- **文件:** `backend/app/services/chat_service.py`, `backend/app/tests/test_chat_citations.py`
- **问题:** 同一 chunk_id 可能出现多次 → Vue duplicate key + 重复胶囊
- **修复:** 持久化前按 chunk_id 去重
- **测试:** 构造重复 chunk_id 的 citation，断言去重

### Task 3 (P1-3): Parse 流程 rollback
- **文件:** `backend/app/api/v1/endpoints/parse.py`, `backend/app/tests/test_security_scan.py`
- **问题:** except 直接 commit，可能提交半成品（旧 chunks 已删）
- **修复:** except 中先 `db.rollback()`，再重新查 material 写 failed
- **测试:** mock scanner 抛异常，断言旧 chunks 不丢失

### Task 4 (P0-2): 接通引用胶囊到 chunk 原文 + 高亮
- **文件:** `frontend/src/api/material.ts`, `frontend/src/views/ChatView.vue`
- **问题:** 抽屉只显示 quote_text，不读取完整 chunk 原文
- **修复:** openCitationDrawer 调用 `getChunk(chunk_id)`；前端高亮 quote_text

### Task 5 (P1-2): SSE fallback 防重复保存
- **文件:** `frontend/src/api/chat.ts`, `frontend/src/views/ChatView.vue`
- **问题:** stream 已保存用户消息后 fallback 到 /chat 会重复保存
- **修复:** 仅在未收到任何 SSE 事件时才 fallback

### Task 6 (P2): 清理与一致性
- 移除主界面可靠性等级 + 相关度百分比 UI
- chunks.py ownership join 改为 Material.course_id 链
- 移除 algorithmic-art/ 目录
- 修复 sendMessageStream 硬编码 localhost → 用 Vite proxy

### Task 7: 验收
- 后端全量 pytest 通过
- 前端 npm run build 通过
- HTTP 端点验证
- git commit + push
