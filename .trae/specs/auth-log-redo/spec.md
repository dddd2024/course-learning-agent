# 登录态与日志中心可用性返工 Implementation Plan

> **Goal:** 返工修复两个用户可见问题——旧/无效 localStorage token 绕过登录页、后端不可达时日志中心显示空表——让登录页稳定出现且日志中心能解释离线状态。

**来源:** `课程学习助手_登录态与日志中心可用性返工修复计划.docx`
**基线:** 提交 dce1b9b

**Architecture:** 纯前端修复，后端不变。核心是 auth store token 初始化规则、异步路由守卫、日志中心离线态展示、错误上报限流与 401 保留。

---

## Task A: 彻底修复登录态与路由守卫

**Files:** `frontend/src/stores/auth.ts`, `frontend/src/router/index.ts`, `frontend/src/main.ts`

- [ ] **A1**: auth store 重写 `readInitialToken`：未选择"记住登录"时禁止 fallback 读取 localStorage token，启动即清理历史 localStorage token；新增 `authReady` ref + `ensureAuthReady()`（内部 await `/auth/me`）。
- [ ] **A2**: router `beforeEach` 改 async；受保护路由 await `ensureAuthReady()`，失败跳 `/login?redirect=`；登录页仅在 `ensureAuthReady` 成功后跳 dashboard。
- [ ] **A3**: main.ts 移除盲目补发，改为认证有效后才补发。

## Task B: 日志中心离线态展示

**Files:** `frontend/src/views/LogsView.vue`

- [ ] **B1**: 新增 `backendReachable`/`loadError`/`pendingLocalReports` 状态；GET /logs 失败时不显示"暂无异常日志"，改为"后端不可达，无法加载服务端日志"。
- [ ] **B2**: 本地待上报日志用独立 el-alert 展示；提供"重新连接并补发"按钮。

## Task C: 加固错误上报队列、补发和限流

**Files:** `frontend/src/utils/errorReport.ts`, `frontend/src/api/index.ts`, `frontend/src/utils/error.ts`

- [ ] **C1**: errorReport 导出 `readPendingQueue()`；401 不丢弃 pending（保留队列）；新增 60 秒同类错误去重 + 最多 50 条队列上限。
- [ ] **C2**: 补发必须在认证有效后执行（main.ts 改为 ensureAuthReady 后）。
- [ ] **C3**: index.ts / error.ts：后端不可达时提示"已保存到本地待上报日志，后端恢复并登录后补发"。

## Task D: 后端健康检查与启动提示

**Files:** `frontend/src/api/logs.ts`（或 health.ts）, `frontend/src/views/LogsView.vue`

- [ ] **D1**: 新增 lightweight `checkBackendHealth()`（GET /api/v1/health，带 skipReport 标记）；失败只更新连接状态，不写服务端日志。
- [ ] **D2**: LogsView 顶部增加"后端服务状态"区域：成功显示项目标识+时间；失败显示 8000 端口与启动脚本提示。

## Task E: 全量验收 + 提交推送

- [ ] **E1**: 前端 build + 后端 pytest + 验收脚本通过。
- [ ] **E2**: conventional commit + push to `origin/main`。
