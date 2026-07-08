# 稳定性与安全增强实施计划 (Security & Stability Hardening)

> **来源文档**：
> 1. `课程学习助手_稳定性与Windows启动器收尾修复方案.docx`（Phase 1）
> 2. `课程学习助手_用户信息安全与加密增强计划.docx`（Phase 2）
>
> **执行顺序**：稳定性文档明确要求"先修稳定性，再做安全增强"。Phase 1 全部完成并验收后，再进入 Phase 2。

**目标**：补齐上次审计遗留的稳定性与 Windows 启动器收尾问题，再实施用户敏感信息保护增强（日志脱敏、Token 存储、邮箱脱敏、密钥轮换、安全状态卡片）。

**架构**：FastAPI + SQLAlchemy（SQLite 开发库）+ Vue3 + TypeScript + Element Plus。后台任务改用独立 SessionLocal；日志统一脱敏；前端 token 改 sessionStorage + 401 自动登出；新增 LLM API Key 轮换脚本与安全状态卡片。

**技术栈**：Python 3.10 / FastAPI / SQLAlchemy / pytest / Vue3 / Vite / Element Plus / PowerShell

---

## Phase 1：稳定性与 Windows 启动器收尾（来自稳定性文档）

### Task 1：后台解析数据库会话隔离（稳定性 Task A，最高优先级）

**问题**：当前 `parse.py` 的 `_run_parse_in_background` 复用请求级 `db` Session。FastAPI 在后台任务完成后才关闭请求 Session，长任务可能引发连接问题，且异常时无法兜底恢复。

**文件**：
- 修改：`backend/app/api/v1/endpoints/parse.py`
- 测试：`backend/app/tests/test_parse_background_session.py`（新建）

**实现**：
- `_run_parse_in_background` 签名改为只接收 `material_id, user_id`，内部用 `SessionLocal()` 新建会话。
- 异常兜底：catch Exception → rollback → material 置 `failed` + `error_message` + `last_parse_error` + `parse_finished_at` + `log_error(category="parse")`。
- endpoint 中 `background_tasks.add_task(_run_parse_in_background, material_id, current_user.id)`，不再传 db。

**验收**：
- POST /parse 仍立即返回 processing。
- 后台任务完成 → ready/failed。
- 后台任务异常 → material 变 failed，不永久卡 processing。
- 测试 monkeypatch `SessionLocal` 或 `parse_with_retry` 抛异常验证兜底。

### Task 2：上传失败磁盘残留清理（稳定性 Task B）

**问题**：`write_bytes` 部分写入后抛 OSError 会残留半文件。

**文件**：
- 修改：`backend/app/api/v1/endpoints/materials.py`
- 测试：`backend/app/tests/test_material_upload_error_log.py`（追加用例）

**实现**：在 `except OSError` 分支中，先 `absolute_path.unlink(missing_ok=True)`，再尝试 `absolute_path.parent.rmdir()`（只删空目录，OSError 静默忽略），然后删 Material 记录 + 写日志。

### Task 3：Windows 启动器首次运行初始化（稳定性 Task C）

**问题**：`start_windows.ps1` 未创建 venv / 未安装后端依赖 / 未 init_db，新环境无法直接启动。

**文件**：
- 修改：`scripts/start_windows.ps1`

**实现**：启动前增加：venv 不存在则 `python -m venv`；`pip install -r requirements.txt`；`python scripts/init_db.py`。流程顺序：定位 repoRoot → 检查 Python → 创建 venv → 装后端依赖 → init_db → 检查 Node/npm → npm install（如缺）→ 启动后端 → 健康检查 → 启动前端 → 打开 app。

### Task 4：Windows 停止脚本与 PID 管理（稳定性 Task D）

**问题**：隐藏窗口启动的后端/前端无法方便关闭，关 app 窗口不关服务。

**文件**：
- 修改：`scripts/start_windows.ps1`（启动后写 PID 文件）
- 新建：`scripts/stop_windows.ps1`

**实现**：
- start_windows.ps1 启动后端/前端时用 `Start-Process -PassThru`，把 PID 写入 `logs/dev-server/backend.pid` / `frontend.pid`。
- stop_windows.ps1 读 PID 文件 → `Stop-Process -Id $pid -Force` → 删 PID 文件。兜底检查 8000/5173 端口，若仍由本项目进程占用则提示。不粗暴杀所有 node/python，必须通过 PID + 端口 + 命令行路径确认。

### Task 5：端口复用准确性与前端项目标识（稳定性 Task E）

**问题**：5173 端口只要 HTTP 200 就复用，可能误连其他 Vite 项目。

**文件**：
- 修改：`frontend/index.html`（title + meta app-name）
- 修改：`scripts/start_windows.ps1`（复用前校验页面内容）

**实现**：
- index.html：`<title>课程学习助手</title>` + `<meta name="app-name" content="course-learning-agent" />`
- start_windows.ps1 复用 5173 时：`Invoke-WebRequest` 后检查 Content 是否含 `course-learning-agent` 或 `课程学习助手`，否则报错退出。

---

## Phase 2：用户信息安全与加密增强（来自安全文档）

### Task 6：日志敏感字段脱敏（安全 Task B，P1 最高优先级）

**问题**：错误日志可能混入 Authorization、api_key、password、token、sk- 等。

**文件**：
- 修改：`backend/app/services/error_logger.py`（写入前脱敏 message/technical_detail）
- 测试：`backend/app/tests/test_error_log_redaction.py`（新建）

**实现**：在 `log_error` 中对 `message` 与 `technical_detail` 调用 `redact_sensitive(text)`：
- `Authorization: Bearer <token>` → `Authorization: Bearer ***`
- `api_key`/`apiKey`/`password`/`token` 字段值 → `***`
- `sk-` 开头片段 → `sk-***`
- JWT 三段式（`ey...ey...sig`）→ `<jwt:***>`

### Task 7：JWT 与前端 Token 存储降风险（安全 Task D，P2）

**文件**：
- 修改：`backend/app/core/config.py`（ACCESS_TOKEN_EXPIRE_MINUTES 10080 → 480）
- 修改：`frontend/src/stores/auth.ts`（默认 sessionStorage，"记住登录"用 localStorage）
- 修改：`frontend/src/api/index.ts`（从 auth store 读 token，401 已有自动登出）
- 测试：`backend/app/tests/test_auth_security.py`（新建）

**实现**：
- 后端默认过期 480 分钟（8 小时），生产可配置。
- auth store：`setToken(token, name, remember=false)`，remember=true 用 localStorage，否则 sessionStorage。初始化优先读 sessionStorage 再读 localStorage。
- axios 请求拦截器改从 auth store（而非直接 localStorage）取 token。
- 后端测试：token 过期校验、login 返回 token_type。

### Task 8：邮箱脱敏展示（安全 Task C1，P3）

**文件**：
- 修改：`backend/app/schemas/user.py`（UserResponse 增加 `email_masked` 字段，保留 `email` 兼容）
- 修改：`backend/app/api/v1/endpoints/auth.py`（register/me 返回 email_masked）
- 测试：`backend/app/tests/test_auth_security.py`（追加邮箱脱敏用例）

**实现**：
- `mask_email("alice@example.com")` → `"a***@e***.com"`。
- UserResponse 增加 `email_masked: str | None`，`email` 字段保留但可选置空（不破坏契约）。
- 不加密 username（保持明文用于登录/索引）。

### Task 9：LLM API Key 轮换脚本（安全 Task E，P4）

**文件**：
- 新建：`scripts/rotate_llm_config_secret.py`
- 测试：`backend/app/tests/test_llm_config_security.py`（新建，含轮换逻辑单元测试）

**实现**：
- 参数：`--old-secret`、`--new-secret`、`--dry-run`/`--apply`。
- 流程：用 old-secret 解密所有 `llm_configs.api_key_encrypted`，用 new-secret 重新加密回写。
- dry-run 只打印将影响多少条；apply 实际写入并校验可解密。
- 生成新 Fernet key 提示：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`。

### Task 10：个人中心安全状态卡片（安全 Task F，P5）

**文件**：
- 修改：`backend/app/api/v1/endpoints/auth.py`（新增 GET /auth/security-status）
- 修改：`backend/app/schemas/user.py`（SecurityStatusResponse）
- 修改：`frontend/src/api/auth.ts`（getSecurityStatus）
- 修改：`frontend/src/views/ProfileView.vue`（安全状态卡片）
- 测试：`backend/app/tests/test_auth_security.py`（追加）

**实现**：
- 后端返回：`password_storage="bcrypt_hash"`、`api_key_storage="fernet_encrypted"`、`token_expiry_minutes`、`environment`、`using_default_secret`（仅开发环境返回，生产不暴露）。
- 前端 ProfileView 顶部新增"安全状态"卡片，展示上述字段；开发环境 + 默认密钥显示警告提示。
- API Key 一律显示 masked，不提供复制明文。

### Task 11：测试与验收（安全 Task G）

**文件**：
- `test_auth_security.py`：登录、token 过期、邮箱脱敏、安全状态接口
- `test_llm_config_security.py`：轮换脚本逻辑、API Key 不返回明文
- `test_error_log_redaction.py`：各敏感字段脱敏规则

**验收命令**：
- `cd backend && python -m pytest app/tests/ -q`
- `cd frontend && npm run build`
- `scripts/verify_phase2_engineering.ps1`

---

## 执行约束

- 不做 Electron/Tauri 打包。
- 不改 RAG/问答/知识点/计划生成等核心业务逻辑。
- username 保持明文（登录/唯一索引需要）。
- 不加密课程资料文件（影响解析/检索/演示）。
- 不删除现有 Agent 审计和日志中心功能。
- 每个 Task 完成后运行相关测试，全部完成后运行全量验收。

## 最终完成定义

Phase 1：
1. 解析后台任务持有独立 DB 会话，异常可恢复、可记录，不长期卡 processing。
2. 上传失败时数据库与磁盘均不留半成品。
3. Windows 桌面快捷方式可在新环境稳定启动。
4. stop_windows.ps1 可安全关闭隐藏运行的前后端。
5. 端口复用只复用本项目服务。

Phase 2：
6. error_logs 不含 Bearer/JWT/password/api_key/sk- 明文。
7. 前端默认不长期保存 token；401 自动登出。
8. 个人中心展示安全状态，不泄露凭据。
9. LLM API Key 支持密钥轮换脚本。
10. 新增测试全部通过，frontend build 通过。
