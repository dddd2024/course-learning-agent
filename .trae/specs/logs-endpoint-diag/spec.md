# 日志中心可达但加载失败与补发失败修复 — 实施计划

> **执行方式：** TDD（先写失败测试 → 实现 → 验证通过），使用 `scripts/verify_phase2_engineering.ps1` 静态检查 + 后端 pytest 作为验收夹具。

**目标：** 修复"后端 health 可达但 /logs 加载失败、pending 补发失败"的闭环问题。把日志中心拆成三层状态（后端健康、认证、/logs 业务接口），补发前强制验证登录态，/logs 自身错误不进入 pending 递归。

**根因（来自计划文档）：**
1. health 是公开接口但 /logs 需要登录；前端 token 过期时 /logs 返回 401，UI 只显示"日志加载失败"，不跳登录。
2. handleReconnectAndFlush 只验证 health，没验证登录态；token 失效时 POST /logs 返回 401，pending 保留但提示含糊。
3. GET /logs 自身失败时被 axios interceptor 记录为 pending，形成"日志系统错误进入日志系统"的递归污染。
4. UI 缺少 /logs 接口状态层（status code、message、detail、requestUrl），用 health ok 替代业务接口 ok。

---

## Task A：LogsView 增加 /logs 业务接口诊断状态

**Files:**
- Modify: `frontend/src/views/LogsView.vue`

**A1 — 新增 logsEndpointStatus 状态**
- 新增 type `LogsEndpointStatus = 'unknown' | 'ok' | 'auth_failed' | 'forbidden' | 'server_error' | 'client_error' | 'unreachable'`
- 新增 ref `logsEndpointStatus`、`lastLogsError`（含 statusCode、serverMessage、serverDetail、requestUrl）

**A2 — fetchLogs catch 记录详细错误**
- 读取 `err.response.status`、`err.response.data.message`、`err.response.data.detail`、`err.config.url`
- 401 → logsEndpointStatus='auth_failed' + auth.clearToken() + 跳转 /login?redirect=/logs
- 403 → 'forbidden'；500+ → 'server_error'；4xx → 'client_error'；无 response → 'unreachable'
- emptyText 根据 logsEndpointStatus 区分（不再只看 backendConn）

**A3 — 诊断面板新增 /logs 探测按钮**
- "探测 /logs 接口"按钮：调用 listErrorLogs({page_size:1})，结果显示 status code

**A4 — 401 自动跳登录**
- fetchLogs 401 时调用 `auth.clearToken()` + `router.push('/login?redirect=/logs')`

**测试：** acceptance script 静态检查 LogsView.vue 含 `logsEndpointStatus`、`lastLogsError`、`auth_failed`、`/login?redirect=/logs`

---

## Task B：补发 pending 前强制验证登录态

**Files:**
- Modify: `frontend/src/views/LogsView.vue`
- Modify: `frontend/src/utils/errorReport.ts`

**B1 — handleReconnectAndFlush 先验证登录**
- 开头 `const ok = await useAuthStore().ensureAuthReady()`
- 返回 false → 不 flush，提示"请重新登录后补发"，跳 /login?redirect=/logs，pending 保留

**B2 — flushPendingErrorReports 返回结构化结果**
- 返回 `{ sentCount: number, retainedCount: number, retainedReasons: string[] }`
- UI 显示具体原因（auth_failed / server_500 / unreachable）而非笼统提示

**B3 — 登录成功后自动 flush**
- LoginView 登录成功后检查 pending queue，非空则 flushPendingErrorReports

**测试：** acceptance script 检查 errorReport.ts 的 flushPendingErrorReports 返回 sentCount/retainedCount/retainedReasons

---

## Task C：禁止 /logs 自身错误进入 pending 递归

**Files:**
- Modify: `frontend/src/api/index.ts`

**C1 — interceptor 识别 /logs 路径跳过 report**
- 在 interceptor 中，若 `url` 以 `/logs` 开头（GET /logs、GET /logs/{id}、POST /logs、POST /logs/{id}/resolve），默认 skipReport
- 保留其他业务接口（/dashboard/summary、/materials、/plans 等）的错误上报

**测试：** acceptance script 检查 api/index.ts 含 /logs 路径识别逻辑

---

## Task D：onMounted 时序收尾 + 127.0.0.1 统一

**Files:**
- Modify: `frontend/src/views/LogsView.vue`
- Modify: `scripts/start_windows.ps1`

**D1 — onMounted 改为 async 顺序执行**
- `await checkHealth(); await fetchLogs(); refreshPending(); if (failed) runDiagnostics()`
- 避免 health 和 logs 并发导致状态互相覆盖

**D2 — start_windows.ps1 frontendUrl 统一 127.0.0.1**
- `$frontendUrl = "http://127.0.0.1:$frontendPort"`（当前是 localhost）

**测试：** acceptance script 检查 start_windows.ps1 frontendUrl 含 127.0.0.1

---

## Task E：验收脚本 + 全量验证 + 提交推送

**Files:**
- Modify: `scripts/verify_phase2_engineering.ps1`

**E1 — 新增静态检查段**
- 检查 LogsView.vue 含 logsEndpointStatus、lastLogsError、auth_failed、/login?redirect=/logs
- 检查 errorReport.ts 的 flushPendingErrorReports 返回 sentCount/retainedCount/retainedReasons
- 检查 api/index.ts 含 /logs 路径跳过 report 逻辑
- 检查 start_windows.ps1 frontendUrl 含 127.0.0.1

**E2 — 全量验证**
- 后端 pytest（无后端改动，验证无回归）
- 前端 npm run build
- pwsh verify_phase2_engineering.ps1 -SkipBackend

**E3 — 提交推送**
- 删除 .docx
- conventional commit + push origin main
