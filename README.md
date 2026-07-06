# 课程学习助手 Agent 平台

面向高校学生的课程学习助手 Agent 平台。用户上传课程资料后，平台自动
解析、切块、提取知识点，并基于 RAG（检索增强生成）回答课程问题、生成
测验、规划学习计划，全程带有引用追溯与 Agent 执行审计。

## 技术栈

- 后端：FastAPI + SQLAlchemy 2.x + SQLite（可切换其他数据库）
- 前端：Vue 3 + Vite + Element Plus + Pinia + Vue Router
- 认证：JWT（python-jose + passlib/bcrypt）
- RAG Agent：自研 Agent 编排（OutlineAgent / CourseQAAgent /
  PlannerAgent / QuizAgent / CitationVerifyAgent），通过统一的
  `call_llm` 适配层接入大模型，无 API Key 时自动降级为 mock 模式
- 文件解析：txt / pdf / docx / md / pptx（pypdf、python-docx、python-pptx）

## 功能特性

- 用户认证：注册、登录、JWT 鉴权，所有数据按用户隔离
- 课程管理：多课程创建与维护（教师、学期、颜色标识）
- 资料上传与解析：支持 txt / pdf / docx / md / pptx，自动切块（带章节标题识别）
- 检索：基于关键词的切块检索，支持检索结果可视化（命中切块与得分）
- RAG 问答：基于课程资料的多轮对话式问答，答案附带引用
- 引用追溯：每条引用记录来源切块、引用原文、支撑理由与置信度
- 知识点：OutlineAgent 从资料中提取知识点，标注重要度、考查方式与复习建议
- 学习计划：PlannerAgent 将学习目标分解为任务，scheduler 排程为每日待办
- 多课程规划：跨课程统筹安排每日学习任务，避免时间冲突
- 测验与薄弱点：QuizAgent 生成题目，作答后自动记录 WeakPoint 并反馈
- Agent 审计：每次 Agent 运行记录输入、输出、步骤与耗时，便于复盘
- 检索可视化：直观展示命中的资料切块及其匹配信息
- 可靠性等级：基于引用验证与置信度给出回答可靠性评级
- 用户级大模型配置中心：个人中心支持 OpenAI / DeepSeek / 通义千问 / 智谱 / 自定义等 OpenAI 兼容模型，API Key 加密存储
- 真实 OpenAI-compatible LLM 调用：三层 fallback（用户配置 > 系统配置 > mock）
- 资料解析支持 TXT / PDF / DOCX / MD / PPTX 五种格式
- Agent 审计增强：每次运行记录 provider / model / config_id，便于追溯具体模型来源

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- npm 9+（随 Node 安装）

### 后端启动

在 `backend` 目录下执行：

```powershell
# 1. 创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # PowerShell
# 或 .venv\Scripts\activate.bat  # cmd

# 2. 安装依赖
pip install -r requirements.txt

# 3. 初始化数据库表
python ..\scripts\init_db.py

# 4. 写入演示数据（可选，推荐首次体验时执行）
python scripts\seed_demo_data.py

# 5. 启动后端开发服务器
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端启动后访问 API 文档：<http://localhost:8000/docs>

### 前端启动

在 `frontend` 目录下执行：

```powershell
npm install
npm run dev
```

前端默认运行在 <http://localhost:5173>，已通过 Vite 代理将
`/api` 请求转发到后端 8000 端口。

### 个人中心配置大模型（可选）

登录后点击右上角用户头像进入「个人中心」（`ProfileView`），可在
「大模型配置」区域填写自己的模型信息：

1. 选择 provider（OpenAI / DeepSeek / 通义千问 / 智谱 / 自定义）
2. 填写 API Key、Base URL、模型名称（如 `gpt-4o-mini`、
   `deepseek-chat`、`qwen-plus`、`glm-4` 等）
3. 可按需调整 temperature、max_tokens、timeout
4. 保存后即可在该用户的所有 Agent 调用中生效；API Key 经
   Fernet 对称加密后写入数据库，明文不会落库

个人中心配置仅对当前用户生效，不影响其他用户与系统默认配置。
若不配置，平台将按系统 `.env` 配置或 mock 模式运行（详见下文
「LLM 配置策略」）。

### 一键启动（Windows PowerShell）

项目根目录提供了一键启动脚本，会分别在新窗口中启动前后端：

```powershell
.\scripts\run_dev.ps1
```

脚本启动后会打印访问地址与 demo 账号，按任意键即可关闭前后端窗口。

## 配置说明

后端配置通过环境变量读取（`backend/app/core/config.py`）。将
`backend/.env.example` 复制为 `backend/.env` 并按需修改：

| 变量名                       | 说明                                       | 默认值                          |
| ---------------------------- | ------------------------------------------ | ------------------------------- |
| `DATABASE_URL`               | 数据库连接字符串                           | `sqlite:///./course_assistant.db` |
| `JWT_SECRET_KEY`             | JWT 签名密钥，生产环境务必更换             | `change_me`                     |
| `JWT_ALGORITHM`              | JWT 签名算法                               | `HS256`                         |
| `ACCESS_TOKEN_EXPIRE_MINUTES`| Access Token 有效期（分钟）                | `10080`                         |
| `UPLOAD_DIR`                 | 上传文件存储目录                           | `../storage/uploads`            |
| `PARSED_DIR`                 | 解析结果存储目录                           | `../storage/parsed`             |
| `LLM_PROVIDER`               | LLM 提供方，`mock` 或 `real`               | `mock`                          |
| `LLM_API_KEY`                | 真实 LLM 的 API Key（mock 模式留空）       | 空                              |
| `EMBEDDING_PROVIDER`         | 向量嵌入提供方                             | `mock`                          |
| `MAX_UPLOAD_MB`              | 单个文件上传大小上限（MB）                 | `30`                            |

## 默认账号

执行 `seed_demo_data.py` 后会创建演示账号：

- 用户名：`demo`
- 密码：`demo123456`

## API 文档

后端启动后，OpenAPI 交互式文档位于：
<http://localhost:8000/docs>

主要接口分组（前缀 `/api/v1`）：

- `/auth` 认证
- `/courses` 课程、资料、知识点、薄弱点
- `/materials` 资料解析
- `/search` 检索
- `/conversations`、`/chat` 对话与 RAG 问答
- `/messages` 引用
- `/plans`、`/todos` 学习计划与待办
- `/quizzes` 测验
- `/agent-runs` Agent 审计

## 项目结构

```
course-learning-agent/
├── backend/                # FastAPI 后端
│   ├── app/
│   │   ├── agents/         # Agent 编排与 LLM 适配层
│   │   ├── api/v1/endpoints/ # 各资源 REST 接口
│   │   ├── core/           # 配置、数据库、安全、异常
│   │   ├── models/         # SQLAlchemy ORM 模型
│   │   ├── retrieval/      # 文件解析、切块、检索
│   │   ├── schemas/        # Pydantic 请求/响应模型
│   │   ├── services/       # 计划排程等服务
│   │   └── main.py         # 应用入口
│   ├── scripts/
│   │   └── seed_demo_data.py # 演示数据初始化脚本
│   ├── requirements.txt
│   └── .env.example        # 环境变量示例
├── frontend/               # Vue3 + Vite 前端
│   ├── src/
│   │   ├── api/            # 后端接口封装
│   │   ├── layouts/        # 布局组件
│   │   ├── router/         # 路由
│   │   ├── stores/         # Pinia 状态
│   │   ├── views/          # 页面
│   │   └── main.ts
│   └── package.json
├── storage/                # 运行时生成：上传与解析结果存储
├── scripts/
│   ├── init_db.py          # 建表脚本
│   └── run_dev.ps1         # 一键启动脚本
└── README.md
```

## LLM 配置策略

平台通过统一的 `call_llm` 适配层接入大模型，采用三层 fallback
机制决定本次调用使用哪一份配置，优先级从高到低为：

1. **用户配置（最高优先级）**：用户在「个人中心」配置并启用的
   模型。若该用户存在启用中的配置，Agent 调用将优先使用其
   provider / base_url / model / api_key 等参数。
2. **系统 `.env` 配置**：当用户未配置个人模型时，回退到后端
   `backend/.env` 中的系统级配置，相关变量包括：
   - `LLM_PROVIDER`：`mock` 或 `real`
   - `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`：真实模型接入参数
   - `LLM_TIMEOUT_SECONDS`、`LLM_TEMPERATURE`、`LLM_MAX_TOKENS`：
     调用超时、采样温度与最大 token 数
   - `LLM_CONFIG_SECRET_KEY`：Fernet 密钥，用于加密存储用户级 API Key
3. **mock 兜底（最低优先级）**：当以上两层均不可用时（无用户配置且
   `LLM_PROVIDER=mock` 或真实调用失败），`call_llm` 返回结构化、
   确定性的 mock 响应，确保所有 Agent 流程可完整演示。

### 用户如何配置自己的模型

登录后进入「个人中心」，在「大模型配置」区域填写 provider、
API Key、Base URL、模型名称等信息并保存。保存后该配置立即对
当前用户的所有 Agent 调用生效。API Key 使用 `LLM_CONFIG_SECRET_KEY`
派生的 Fernet 密钥加密后写入数据库，调用时再解密传入模型 SDK。

### mock 模式无需 API Key 即可演示

若只想体验平台功能，无需申请任何大模型 API Key：保持 `.env` 中
`LLM_PROVIDER=mock`（默认值）即可，所有 Agent 流程（问答、知识点
提取、学习计划、测验、引用验证等）均会以确定性 mock 响应运行，
前端功能完整可演示。

## Mock 模式说明

当未配置真实的 LLM API Key（即 `LLM_PROVIDER=mock`）时，平台的
`call_llm` 适配层会返回结构化、确定性的 mock 响应，覆盖以下 Agent：

- `course_qa` 课程问答
- `outline` 知识点提取
- `planner` 学习计划
- `task_decompose` 任务分解
- `multi_course_schedule` 多课程排程
- `quiz_generate` 测验生成
- `citation_verify` 引用验证

这意味着在没有大模型 API Key 的情况下，所有 Agent 流程仍可完整演示，
前端全部功能均可体验。如需接入真实大模型，将 `LLM_PROVIDER` 设为
`real` 并填写 `LLM_API_KEY` 等配置即可（真实适配层按 OpenAI 兼容接口
实现）。

## CI 持续集成

项目通过 GitHub Actions（配置见 `.github/workflows/ci.yml`）在
每次 push 到 `main` 分支或提交 pull request 时自动执行以下两个
并行 job：

- **backend-test**：在 Ubuntu + Python 3.11 环境下安装
  `backend/requirements.txt`，以 `LLM_PROVIDER=mock` 运行
  `python -m pytest app/tests/ -v`，确保后端全部测试用例通过。
- **frontend-build**：在 Ubuntu + Node 20 环境下执行
  `npm ci` 与 `npm run build`（`vue-tsc` 类型检查 + Vite 生产构建），
  确保前端类型正确且可成功构建。

任一 job 失败都会在 PR / commit 上显示红色状态标记，便于在合入
前发现回归问题。
