# 前端交互与日志一致性收尾 Implementation Plan

> **Goal:** 五项收尾修复——路由守卫基于 auth store、隐藏默认密钥提示、合并 Agent 审计入口、前端错误上报到日志中心、错误文案优化——让系统在演示和答辩上更稳。

**来源:** `课程学习助手_前端交互与日志一致性收尾修复计划.docx`

**Architecture:** 不新增大功能。B/C/D 是纯前端改动；A 需要新增 `POST /logs` 后端端点（TDD）+ axios interceptor + 本地暂存补发；E 优化 `parseApiError` 文案。所有日志经 `redact_sensitive` 脱敏。

**Tech Stack:** FastAPI + Pydantic v2 / pytest / Vue 3 + TS + Pinia + Element Plus

---

## Task B: 修复登录状态与路由守卫

**Files:**
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/stores/auth.ts` (新增 token 有效性校验)

- [ ] **B1**: 路由守卫改为读 `useAuthStore().token`，不再 `localStorage.getItem('token')`；无效 token 清理并跳 `/login`。
- [ ] **B2**: auth store 新增 `validateToken()` 调用 `/auth/me`，401 时清理 token。

## Task C: 隐藏普通用户的默认密钥提示

**Files:**
- Modify: `frontend/src/views/ProfileView.vue`

- [ ] **C1**: 移除 `using_default_secret` 的 `el-alert` 橙色提示（保留后端生产拒绝启动逻辑不变）。

## Task D: 合并 Agent 审计入口到日志中心

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue`
- Modify: `frontend/src/views/LogsView.vue`（可选：日志详情内链到 AgentRun）

- [ ] **D1**: 侧边栏移除"Agent 审计"菜单项；保留 `/agent-runs` 路由与 `AgentRunsView` 不变（作为内部详情入口）。

## Task A: 前端错误上报到日志中心

**Files:**
- Create: `backend/app/schemas/frontend_error_report.py`（或扩展 general_error_log）
- Modify: `backend/app/api/v1/endpoints/general_error_logs.py`（新增 `POST /logs`）
- Modify: `backend/app/tests/test_general_error_logs.py`
- Modify: `frontend/src/api/logs.ts`（新增 `reportErrorLog`）
- Modify: `frontend/src/api/index.ts`（axios error interceptor 上报）
- Create: `frontend/src/utils/errorReport.ts`（脱敏 + 本地暂存 + 补发）

- [ ] **A1 RED**: 后端测试 `POST /logs` 创建前端上报日志，校验字段、脱敏、不递归。
- [ ] **A2 GREEN**: 新增 `POST /logs` 端点 + schema，复用 `log_error`（自动脱敏）。
- [ ] **A3**: 前端 `reportErrorLog` + axios interceptor（非 401 错误上报；上报接口本身用 `skipReport` 标记防递归）。
- [ ] **A4**: 后端不可达时本地暂存（sessionStorage），恢复后补发。

## Task E: 错误提示文案优化

**Files:**
- Modify: `frontend/src/utils/error.ts`

- [ ] **E1**: `parseApiError` 区分网络异常（无 response，提示后端可能未启动/端口占用）vs 业务错误；文案更具体。

## Task F: 全量验收 + 提交推送

- [ ] **F1**: 后端 pytest + 前端 build + 验收脚本通过。
- [ ] **F2**: conventional commit + push to `origin/main`。
