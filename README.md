# 课程学习助手 Agent 平台

面向高校学生的课程学习助手 Agent 平台。系统围绕“课程—资料—知识点—学习任务”组织数据，支持课程资料解析、文档学习、基于资料的问答与引用、知识点整理、知识图谱、测验、薄弱点分析、单课程/多课程学习计划，以及 Agent 运行审计。

发布说明见 [`docs/engineering/releases/v1.0.0.md`](docs/engineering/releases/v1.0.0.md)。

## 当前实现边界

- 默认数据库为 SQLite。检索、FTS5 索引和部分兼容迁移逻辑以 SQLite 为主要运行环境；将 `DATABASE_URL` 改为其他数据库并不等于可以无适配直接切换。
- 当前检索链路优先使用 SQLite FTS5 + BM25，并在 FTS5 不可用或无结果时回退到关键词检索。`vector_search` 仍是预留接口，尚未启用向量召回。
- 默认 `LLM_PROVIDER=mock`。Mock 模式用于无 API Key 演示完整流程，其输出是确定性的结构化结果，不代表真实大模型效果。
- 真实模型通过 OpenAI-compatible Chat Completions 接口接入。运行时采用“用户配置 → 系统配置 → mock”降级链路，并记录实际 provider、model、fallback 与 degraded 状态。

## 主要功能

### 课程与资料

- 注册、登录和 JWT 鉴权，业务数据按用户隔离。
- 创建和维护多门课程，包含课程名称、教师、学期和颜色标识。
- 上传、查看、重新解析和管理课程资料。
- 支持 TXT、Markdown、PDF、DOCX、PPTX 五种资料格式。
- PDF/PPTX 解析保留页码、阅读顺序、标题、列表层级、表格和图片锚点等结构信息。
- 文档学习页提供“原页 / 结构化文本 / 原文”三种阅读模式、目录、阅读进度、内容速览和文档预览修复。

### 检索、问答与引用

- SQLite FTS5 BM25 检索，支持别名扩展和命中片段展示。
- FTS5 不可用或无结果时，回退到 SQLite `LIKE` 关键词检索；回退评分为标题 2 倍、资料名 2 倍、正文 1 倍，并结合关键词覆盖率等因素。
- 基于课程资料的多轮问答，回答附带来源片段、引用原文、支撑理由和置信度。
- 引用校验、证据不足处理和回答可靠性等级。
- 可从回答引用定位到对应资料、页码和内容片段。

### 知识整理与学习闭环

- 从资料中生成知识点大纲，记录重要度、考查方式和复习建议。
- 构建用户知识图谱，支持按课程/关系/状态筛选、关系确认或驳回，以及两个概念的对比报告。
- 生成测验、提交作答、记录错题和薄弱点。
- 将学习目标拆解为阶段任务和每日待办。
- 支持跨课程计划、任务状态流转、完成记录和学习历史。
- 学习任务可跳转到对应资料学习页，并回写本次学习完成状态。

### Agent、模型与日志

- 统一 `call_llm` 适配层接入 OpenAI-compatible 模型。
- 个人中心可维护用户级模型配置，API Key 加密存储，接口只返回脱敏值。
- Agent 运行记录输入、输出、步骤、耗时、provider、model、config_id、fallback 链路和降级状态。
- 提供 Agent 审计页、日志中心、错误日志接口和仪表盘。

## 技术栈

- 后端：FastAPI、SQLAlchemy 2.x、Pydantic 2、SQLite、PyMuPDF、pypdf、python-docx、python-pptx、httpx
- 前端：Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router、vis-network
- 认证与安全：JWT、python-jose、passlib/bcrypt、Fernet
- 测试：pytest、Vitest、Playwright
- CI：GitHub Actions

## 环境要求

- Python 3.10+
- Node.js 20.19+；也可使用 22.12+ 或 24+
- npm（随 Node.js 安装）
- Windows 一键启动脚本需要 PowerShell

> 当前前端依赖包含 Vite 8 和相关工具链，Node.js 18 不满足已锁定依赖的 engine 要求。

## 快速开始

### Windows 推荐启动方式

在项目根目录执行：

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start_windows.ps1
```

该脚本会：

1. 检查 Python、Node.js、npm 和项目结构；
2. 创建 `backend/.venv`，在首次运行或依赖变化时安装后端依赖；
3. 初始化数据库及旧库兼容字段；
4. 安装缺失的前端依赖；
5. 启动后端和前端并执行健康检查；
6. 使用 Edge 或 Chrome 的应用模式打开前端；
7. 将启动日志和 `launch_status.json` 写入 `logs/dev-server/`。

停止由启动器创建的进程：

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\stop_windows.ps1
```

创建桌面快捷方式：

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\create_desktop_shortcut.ps1
```

### 开发模式一键启动

需要 Uvicorn/Vite 热更新时，在项目根目录执行：

```powershell
.\scripts\run_dev.ps1
```

该脚本会在两个 PowerShell 窗口中启动后端和前端；在启动脚本窗口按任意键会关闭这两个进程。

### 手动启动

#### 后端

```powershell
cd backend

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 初始化表和兼容迁移
.\.venv\Scripts\python.exe ..\scripts\init_db.py

# 可选：写入 demo 数据。应从 backend 目录执行，
# 以确保默认 SQLite 路径与后端运行时一致。
.\.venv\Scripts\python.exe scripts\seed_demo_data.py

# 启动开发服务器
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端 API 文档：<http://localhost:8000/docs>

#### 前端

```powershell
cd frontend
npm install
npm run dev
```

前端地址：<http://localhost:5173>

### Demo 数据

执行 `backend/scripts/seed_demo_data.py` 后会创建：

- 用户名：`demo`
- 密码：`demo123456`
- 示例课程、资料切块、知识点、学习计划、待办、测验、对话、知识图谱数据和 Agent 审计记录

Seed 脚本是幂等的，重复运行会复用已有记录，不会按正常情况重复插入同一批演示数据。

## 配置说明

后端设置定义在 `backend/app/core/config.py`。可将 `backend/.env.example` 复制为 `backend/.env` 后修改：

```powershell
Copy-Item backend\.env.example backend\.env
```

常用变量：

| 变量 | 用途 |
| --- | --- |
| `ENVIRONMENT` | `development` 或 `production` |
| `DATABASE_URL` | SQLAlchemy 数据库连接字符串 |
| `JWT_SECRET_KEY` | JWT 签名密钥 |
| `JWT_ALGORITHM` | JWT 算法，默认 `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access Token 有效期 |
| `UPLOAD_DIR` / `PARSED_DIR` | 上传文件与解析产物目录 |
| `LLM_PROVIDER` | `mock` 或 `real` |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | 系统级真实模型配置 |
| `LLM_TIMEOUT_SECONDS` | 普通 LLM 调用超时 |
| `LLM_CONCEPT_COMPARE_TIMEOUT_SECONDS` | 概念对比专用超时 |
| `LLM_TEMPERATURE` / `LLM_MAX_TOKENS` | 系统级生成参数 |
| `LLM_CONFIG_SECRET_KEY` | 用户 API Key 加密密钥 |
| `AGENT_TRACE_MODE` | `error`、`always` 或 `off` |
| `CORS_ORIGINS` | 允许的前端来源，逗号分隔 |
| `ALLOW_PRIVATE_LLM_ENDPOINTS` | 是否允许访问私网/localhost 模型地址 |
| `MAX_UPLOAD_MB` | 单文件上传大小上限 |

配置值存在两个层次：

- 未创建 `.env` 时使用 `backend/app/core/config.py` 中的代码默认值，例如 `ACCESS_TOKEN_EXPIRE_MINUTES=480`、`UPLOAD_DIR=../storage/uploads`。
- 复制 `backend/.env.example` 后，示例文件会覆盖部分代码默认值，例如 `ACCESS_TOKEN_EXPIRE_MINUTES=1440`、`UPLOAD_DIR=storage/uploads`。

路径相对于后端进程的当前工作目录解析。推荐始终从 `backend` 目录启动后端，并保持初始化、Seed 和 Uvicorn 使用同一工作目录。

## LLM 配置策略

### 用户级配置

登录后进入“个人中心 → 大模型配置”，填写 provider、API Key、Base URL、模型名称、temperature、max_tokens 和 timeout。

- 配置只对当前用户生效。
- API Key 经 Fernet 加密后存入数据库。
- 返回给前端的配置只包含脱敏 API Key。
- “测试连接”会请求 `{base_url}/chat/completions`，验证网络、鉴权、模型名和 OpenAI Chat Completions 响应结构。

### 调用与降级顺序

1. 当前用户启用的模型配置；
2. 系统 `.env` 中的真实模型配置（仅当 `LLM_PROVIDER=real`）；
3. 确定性 mock 响应。

真实调用失败时会记录 fallback 原因及实际使用的 provider/model。Mock 或 fallback 运行会标记为 degraded，便于在 Agent 审计中区分真实模型结果和演示结果。

### Mock 模式

`LLM_PROVIDER=mock` 时无需 API Key。当前 mock 构造器覆盖课程问答、知识点提取、计划生成、任务拆解、多课程排程、测验生成、引用验证和概念对比等流程。

## API

所有业务接口使用 `/api/v1` 前缀，主要分组如下：

- `/health`
- `/auth`
- `/courses`
- `/materials`
- `/search`
- `/conversations`、`/chat`
- `/messages`、`/chunks`
- `/plans`、`/todos`
- `/quizzes`
- `/agent-runs`
- `/llm-configs`
- `/dashboard`
- `/agent-error-logs`、`/logs`
- `/concept-graph`

启动后在 <http://localhost:8000/docs> 查看完整 OpenAPI 文档。

## 项目结构

```text
course-learning-agent/
├── backend/
│   ├── app/
│   │   ├── agents/              # Agent 与 LLM 适配层
│   │   ├── api/v1/endpoints/    # REST API
│   │   ├── core/                # 配置、数据库、安全、异常
│   │   ├── db/                  # 兼容迁移
│   │   ├── models/              # SQLAlchemy ORM
│   │   ├── retrieval/           # 解析、文档 IR、切块、检索
│   │   ├── schemas/             # Pydantic Schema
│   │   ├── services/            # 业务服务
│   │   └── tests/               # 后端测试
│   ├── scripts/
│   │   └── seed_demo_data.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── config/
│   │   ├── layouts/
│   │   ├── router/
│   │   ├── stores/
│   │   └── views/
│   ├── tests/e2e/
│   ├── package.json
│   └── playwright.config.ts
├── scripts/                     # 启停、初始化、迁移和验收脚本
├── docs/engineering/            # 工程说明、验收基线与发布说明
├── .github/workflows/           # CI 与发布工作流
└── README.md
```

数据库、上传资料、解析产物、日志、测试报告、前端构建目录和本地凭据均属于运行时/本机内容，不应提交到 Git。

## 测试与 CI

本地常用检查：

```powershell
# 后端
cd backend
.\.venv\Scripts\python.exe -m pytest app/tests -q

# 前端
cd ..\frontend
npm run type-check
npm run test
npm run build
```

端到端测试：

```powershell
cd frontend
npx playwright install chromium
npm run test:e2e
```

`.github/workflows/ci.yml` 当前包含五个主要 Job：

1. **Backend Tests**：Python 3.11 + pytest；
2. **Frontend Unit Tests**：Node 20 + TypeScript 类型检查、Vitest、生产构建；
3. **Migration Check**：数据库初始化、迁移 dry-run 和 smoke test；
4. **E2E Tests**：隔离数据库/存储环境中的 Playwright Chromium 测试，并要求失败数和跳过数均为 0；
5. **Acceptance Verification**：依赖前四项，通过 `scripts/verify_function_closure_v7.py` 生成并校验 V7 功能闭环报告。

各 Job 会上传对应测试、迁移、E2E 和验收产物。发布验收结果见 [`docs/engineering/releases/v1.0.0.md`](docs/engineering/releases/v1.0.0.md)。

## 生产部署注意事项

- 设置 `ENVIRONMENT=production`。
- 更换 `JWT_SECRET_KEY` 和 `LLM_CONFIG_SECRET_KEY`；生产环境使用默认密钥会拒绝启动。
- 将 `CORS_ORIGINS` 设置为真实前端域名，生产环境禁止空值和 `*`。
- 默认禁止私网、localhost 和云元数据地址作为 LLM Base URL。仅在明确需要本地模型时评估并设置 `ALLOW_PRIVATE_LLM_ENDPOINTS=true`；云元数据地址始终阻止。
- 使用持久化上传/解析目录并定期备份数据库。
- 通过 Nginx、Caddy 等反向代理启用 HTTPS。
- 当前 FTS5 检索和兼容迁移以 SQLite 为主要目标；切换 PostgreSQL/MySQL 前需要替换相应检索和迁移实现。
