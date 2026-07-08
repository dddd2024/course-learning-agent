# 一键启动后端不可达修复 — 实施计划

> **执行方式：** TDD（先写失败测试 → 实现 → 验证通过），使用 `scripts/verify_phase2_engineering.ps1` 静态检查作为前端/脚本测试夹具，后端使用 pytest。

**目标：** 修复"一键打开后前端可见但后端不可达"的启动链路问题，统一 127.0.0.1/localhost 地址策略，加固启动脚本，让日志中心能诊断启动链路。

**根因：**
1. 前端 `api/index.ts` 与 `api/health.ts` 硬编码 `http://localhost:8000`，而后端监听 `127.0.0.1:8000`，Windows 上 localhost 可能解析到 IPv6 ::1 导致假不可达。
2. `start_windows.ps1` 后端健康检查用 `localhost`，与后端绑定地址不一致。
3. 后端启动失败时脚本仍可能打开前端页面，误导用户。
4. 日志中心不可达时只显示"后端服务不可达"，不显示实际请求地址与 backend.log 路径。

---

## Task A：统一前端 API 地址配置

**Files:**
- Create: `frontend/src/config/api.ts`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/api/health.ts`

**A1 — 新建 `frontend/src/config/api.ts`**
- 导出 `API_BASE_URL`（默认 `http://127.0.0.1:8000/api/v1`，支持 `import.meta.env.VITE_API_BASE_URL` 覆盖）
- 导出 `API_HOST`（`127.0.0.1`）、`API_PORT`（`8000`）
- 导出 `DIAG_HOSTS = ['127.0.0.1', 'localhost']` 用于双地址诊断

**A2 — `api/index.ts` 使用统一配置**
- `baseURL: API_BASE_URL` 替换硬编码 `http://localhost:8000/api/v1`

**A3 — `api/health.ts` 使用统一配置 + 双地址诊断**
- `checkBackendHealth()` 用 `API_BASE_URL`
- 新增 `checkBackendHealthByHost(host: string): Promise<{ host: string; ok: boolean; health?: BackendHealth; error?: string }>` 用于诊断 127.0.0.1 与 localhost 差异

**A4 — 测试（acceptance script 静态检查）**
- 检查 `frontend/src/api/index.ts` 不含硬编码 `localhost:8000`
- 检查 `frontend/src/api/health.ts` 不含硬编码 `localhost:8000`（除了诊断 DIAG_HOSTS）
- 检查 `frontend/src/config/api.ts` 存在并导出 `API_BASE_URL`

---

## Task B：加固 Windows 一键启动脚本

**Files:**
- Modify: `scripts/start_windows.ps1`

**B1 — 后端健康检查统一用 127.0.0.1**
- `$backendUrl = "http://127.0.0.1:$backendPort/api/v1/health"`

**B2 — 后端失败时不打开前端，显示 backend.log 最后 40 行**
- 后端健康检查失败 → 调用 `Show-BackendFailure` 函数打印最后 40 行 → exit 1（不进入前端启动流程）

**B3 — 端口占用显示 PID/进程名/命令行**
- 新增 `Get-PortOwner($port)` 函数返回 PID、进程名、命令行
- 8000/5173 占用且非本项目时输出详细信息与处理建议

**B4 — 不掩盖后端失败**
- 已由 B2 保证（后端先启动，失败即 exit），额外在前端启动前再校验后端仍健康

**B5 — 写 launch_status.json**
- `logs/dev-server/launch_status.json`：backend/frontend health、pid、log path、last_start_time

**测试：** acceptance script 检查 `start_windows.ps1` 含 `127.0.0.1:$backendPort/api/v1/health`、含 `launch_status.json`、含 `Show-BackendFailure` 或等价 tail 逻辑

---

## Task C：桌面快捷方式修复

**Files:**
- Modify: `scripts/create_desktop_shortcut.ps1`
- Create: `scripts/check_shortcut.ps1`

**C1 — 覆盖旧快捷方式提示**
- 检测已存在 .lnk → 输出其 TargetPath/WorkingDirectory → 覆盖写入新路径

**C2 — 新建 `check_shortcut.ps1`**
- 读取桌面 `Course Learning Agent.lnk` → 输出 TargetPath、Arguments、WorkingDirectory、IconLocation

**C3 — 启动成功输出含仓库路径**
- `start_windows.ps1` 成功横幅增加 RepoRoot 行

**测试：** acceptance script 检查 `check_shortcut.ps1` 存在

---

## Task D：日志中心启动链路诊断

**Files:**
- Modify: `frontend/src/views/LogsView.vue`
- Modify: `frontend/src/utils/errorReport.ts`

**D1 — 诊断面板：显示 API_BASE_URL + 双地址 health**
- LogsView 顶部新增折叠诊断卡片：当前 API_BASE_URL、127.0.0.1 检测结果、localhost 检测结果

**D2 — 不可达 banner 显示 backend.log 路径与启动脚本路径**
- 硬编码提示路径（来自 config）

**D3 — "重新连接并补发"先 health 后 flush**
- 已由上一周期 handleReconnectAndFlush 实现，保持

**D4 — pending 队列按 signature 去重展示**
- `errorReport.ts` 入队前检查 signature，已有同类则不重复入队
- LogsView 展示时按 signature 去重

**测试：** acceptance script 检查 `LogsView.vue` 含 `API_BASE_URL`、含 `checkBackendHealthByHost`；`errorReport.ts` 入队前有 signature 去重

---

## Task E：全量验收 + 提交推送

- 后端 pytest（无后端改动，验证无回归）
- 前端 `npm run build`
- `pwsh -File scripts/verify_phase2_engineering.ps1 -SkipBackend`（含新增静态检查）
- 删除 .docx
- conventional commit + push origin main
