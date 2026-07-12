# Health 可达但 Logs 不可达闭环修复 — 实施计划

> **执行方式：** TDD（先写失败测试 → 实现 → 验证通过），后端 pytest + 前端 build + 验收脚本静态检查。

**目标：** 彻底解决"/health 可达但 /logs 不可达时 UI 误报后端不可达、登录 redirect 不闭环、旧后端进程被一键启动误复用、launch_status.json 失败分支不完整"的闭环问题。

**根因（来自计划文档）：**
1. P0-2: `/logs` 无响应时前端把 `backendConn` 改成 `unreachable`，覆盖了 health ok 的结论，导致顶部红条误报"后端服务不可达"。
2. P0-4: LoginView 收到 `redirect=/logs` 后仍固定跳 `/dashboard`，401 跳登录后不能自动回日志中心。
3. P0-5: 全局 401 interceptor 与 LogsView 401 处理重复跳转，redirect 丢失。
4. P0-3: 旧后端进程可能被 health 的 app/version 误判为可复用，新代码已拉取但端口 8000 仍运行旧 commit。
5. P1-1: launch_status.json 不是所有 exit 1 分支都有。
6. P1-2: /logs 探测缺少"无 token/有 token/浏览器错误"拆分。

---

## Task A：LogsView 状态机重构 — health ok 时禁止误报后端不可达

**Files:**
- Modify: `frontend/src/views/LogsView.vue`

**A1 — 新增 browser_no_response 状态**
- `LogsEndpointStatus` 增加 `'browser_no_response'`
- `fetchLogs` 中 status === undefined 时：如果 `backendConn === 'ok'`，则 `logsEndpointStatus = 'browser_no_response'`（不再把 backendConn 改成 unreachable）

**A2 — 顶部 banner 优先级调整**
- health ok 时，即使 /logs 失败，顶部仍显示绿色 health banner
- /logs 失败只在 /logs 状态卡和 emptyText 中展示

**A3 — emptyText 对齐 logsEndpointStatus**
- browser_no_response → "后端健康，但浏览器未收到 /logs 响应（可能是 CORS 或网络拦截）"

**测试：** acceptance script 检查 LogsView.vue 含 `browser_no_response`

---

## Task B：/logs 三层诊断

**Files:**
- Create: `frontend/src/api/logsDiagnostics.ts`
- Modify: `frontend/src/views/LogsView.vue`

**B1 — 新建 logsDiagnostics.ts**
- `probeHealthBare()`: bare axios GET /health，无 Authorization
- `probeLogsNoToken()`: bare axios GET /logs，无 Authorization（预期 401 表示接口可达）
- `probeLogsWithToken(token)`: bare axios GET /logs?page_size=1，带 Authorization
- 返回结构化结果：`{ ok, statusCode, statusText, axiosCode, axiosMessage, serverMessage, serverDetail }`

**B2 — LogsView 诊断面板展示三层结果**
- 点击"探测 /logs 接口"时调用三层探测
- 展示：health 裸请求结果、/logs 无 token 结果（401=可达）、/logs 带 token 结果

**测试：** acceptance script 检查 logsDiagnostics.ts 存在并导出三个探测函数

---

## Task C：LoginView redirect 闭环 + 全局 401 跳转统一

**Files:**
- Modify: `frontend/src/views/LoginView.vue`
- Modify: `frontend/src/api/index.ts`

**C1 — LoginView 读取 redirect 并做白名单校验**
- 引入 `useRoute`，读取 `route.query.redirect`
- 白名单：以 `/` 开头且不以 `//` 开头
- 登录/注册成功后 `router.push(target)` 而非固定 `/dashboard`

**C2 — 全局 401 interceptor 保留 redirect**
- `router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })`
- 如果当前已在 /login，不重复 push

**测试：** acceptance script 检查 LoginView.vue 含 `route.query.redirect` 和白名单校验；api/index.ts 401 含 redirect query

---

## Task D：/health 增加 build 信息 + start_windows.ps1 commit 校验

**Files:**
- Modify: `backend/app/api/v1/endpoints/health.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/tests/test_health.py`
- Modify: `scripts/start_windows.ps1`
- Modify: `frontend/src/api/health.ts`

**D1 — config 增加 APP_GIT_COMMIT / APP_LAUNCH_ID**
- 从环境变量读取，默认空字符串

**D2 — /health 返回 build 字段**
- `build: { git_commit, launch_id, started_at }`

**D3 — 后端测试**
- test_health_returns_build_info：检查 build 字段存在

**D4 — start_windows.ps1 注入 commit + 校验**
- 启动前 `$currentCommit = git rev-parse HEAD`
- `$env:APP_GIT_COMMIT = $currentCommit` 传给 uvicorn
- 端口复用时检查 /health 的 build.git_commit，不匹配则调用 stop_windows.ps1 重启

**D5 — 前端 BackendHealth 接口增加 build 字段**
- 诊断面板显示 backend commit

**测试：** acceptance script 检查 health.py 含 build、start_windows.ps1 含 APP_GIT_COMMIT 和 commit 校验

---

## Task E：launch_status.json 失败闭环 + pending /logs 历史清理

**Files:**
- Modify: `scripts/start_windows.ps1`
- Modify: `frontend/src/utils/errorReport.ts`
- Modify: `frontend/src/views/LogsView.vue`

**E1 — 所有 exit 1 分支写 launch_status.json**
- 检查每个 exit 1 前都有 Write-LaunchStatus

**E2 — pending 队列过滤 /logs 自身历史错误**
- `readPendingQueue()` 过滤掉 request_path 以 `/api/v1/logs` 开头的项
- LogsView 新增"清理 /logs 自身历史错误"按钮

**测试：** acceptance script 检查 errorReport.ts readPendingQueue 过滤 /logs

---

## Task F：验收脚本 + 全量验证 + 提交推送

**Files:**
- Modify: `scripts/verify_phase2_engineering.ps1`

**F1 — 新增静态检查段（section 16）**
- LogsView 含 browser_no_response
- logsDiagnostics.ts 存在并导出 probeLogsNoToken
- LoginView 含 route.query.redirect + 白名单校验
- api/index.ts 401 含 redirect query
- health.py 含 build 字段
- start_windows.ps1 含 APP_GIT_COMMIT + commit 校验
- errorReport.ts readPendingQueue 过滤 /logs

**F2 — 全量验证**
- 后端 pytest
- 前端 npm run build
- pwsh verify_phase2_engineering.ps1 -SkipBackend

**F3 — 提交推送**
- 删除 .docx
- conventional commit + push origin main
