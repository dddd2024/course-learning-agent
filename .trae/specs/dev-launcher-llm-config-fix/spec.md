# 启动脚本与 LLM 配置体验修复 实施计划

> 来源：`课程学习助手_启动与LLM配置体验修复计划.docx`
> 目标仓库：dddd2024/course-learning-agent
> 分支：main

## 背景

项目主体功能与跨课程知识图谱模块已通过 CI，但本地使用暴露两类体验问题：
1. Windows 一键启动脚本因中文编码损坏无法解析（`TerminatorExpectedAtEndOfString`）。
2. 个人中心 LLM 配置测试对 OpenAI-compatible 返回格式假设过强，SenseNova 等真实服务在配置正确时仍报底层 JSON 解析错误。

## 修改目标

- 启动脚本在中文系统/不同编码下稳定运行，具备依赖检查与明确错误提示。
- LLM 配置测试只验证连接/鉴权/模型名/OpenAI-compatible 响应结构，不强制模型正文是 JSON。
- 真实 Agent 调用错误提示可诊断，区分 HTTP 错误、非 JSON 响应、非 OpenAI 格式、模型正文非 JSON。
- 个人中心表单对配置名称/Base URL/模型 ID 含义给出明确提示。
- 文档说明哪些改动支持热更新，哪些必须重启。

## 非目标

- 不引入新供应商 SDK；保持 OpenAI-compatible HTTP 适配。
- 不引入向量/图数据库、Alembic 等新基础设施。
- 不重写个人中心页面；不改变 Agent 业务流程；不删除 mock 模式。

## 任务分解

### Task 1 (P0): 修复 scripts/run_dev.ps1

- 改为 UTF-8 with BOM（或 ASCII 安全）输出，避免 PowerShell 5.1 中文乱码。
- 增加 Python、Node、npm、backend/.venv、frontend/node_modules 检查，缺失给出明确修复命令。
- backend/.venv 缺失时自动创建并 `pip install -r requirements.txt`；frontend/node_modules 缺失时自动 `npm install`。
- 启动前运行 `python scripts/init_db.py`。
- 保留启动前后端 + 按键关闭 + taskkill /T /F 清理。

### Task 2 (P0): 重写 llm_config_service.test_connection

文件：`backend/app/services/llm_config_service.py`

- 不再调用 `_real_response`；改为低层 HTTP 探测 `/chat/completions`。
- 请求体：`model`、`messages=[{role:user, content:"请回复 OK。"}]`、`temperature=0`、`max_tokens=16`；不强制 `response_format`。
- 成功条件：HTTP 2xx + `resp.json()` 成功 + `choices[0].message.content` 存在。
- 失败分类：HTTP 错误（带状态码 + 响应前 300 字符）、响应非 JSON、缺少 choices。
- 不要求 `message.content` 是 JSON。

TDD 测试（TABLE 8）：
- `test_llm_config_connection_success_with_plain_text_content`
- `test_llm_config_connection_reports_http_error`
- `test_llm_config_connection_reports_non_json_response`
- `test_llm_config_connection_reports_missing_choices`

### Task 3 (P0): 优化 _real_response 错误信息 + system message

文件：`backend/app/agents/llm.py`

- `_real_response` 增加 system message 约束只输出 JSON。
- 包装 `resp.json()`、`choices` 路径、`json.loads(content)` 异常为可读 RuntimeError：
  - 模型正文非 JSON → "模型回复不是合法 JSON；请检查 prompt 约束或模型是否支持 JSON 输出。"
  - HTTP 2xx 但响应体不是 JSON → "LLM 服务返回的不是 JSON，可能 Base URL 指向网页/鉴权页/错误页。"
  - 缺少 choices → "LLM 响应不是 OpenAI Chat Completions 格式。"

TDD 测试（TABLE 8）：
- `test_real_response_wraps_content_json_error`
- `test_real_response_wraps_response_json_error`

### Task 4 (P1): 优化 ProfileView.vue 配置表单

文件：`frontend/src/views/ProfileView.vue`

- 配置名称：placeholder 改为「例如：SenseNova DeepSeek V4 Flash」+ help「仅用于区分配置，不是模型 ID」。
- Base URL：placeholder 改为「例如：https://token.sensenova.cn/v1」+ help「不要填写 /chat/completions，系统会自动拼接」。
- 模型：help「填写供应商控制台显示的精确 Model ID，例如 deepseek-v4-flash」。
- API Key：help「仅保存加密后的密文；编辑时留空表示不修改」。
- 测试失败提示：展示后端返回的 error 详情（当前已含 `data.error`，保留并确保可读）。

### Task 5 (P2): 补充启动与热更新说明

文件：`docs/engineering/dev_startup.md`

- 启动脚本使用说明（含 `Set-ExecutionPolicy -Scope Process Bypass`）。
- 热更新/必须重启场景表（后端 Python、前端 Vue/TS、脚本、.env、依赖、数据库结构）。

## 验收

```powershell
# 后端
cd backend; python -m pytest app/tests/ -q
# 前端
cd ../frontend; npm run build
# 工程验收
cd ..; pwsh .\scripts\verify_phase2_engineering.ps1
```

- `scripts/run_dev.ps1` 在 Windows PowerShell 中不再解析失败。
- SenseNova Base URL 在模型正常可用时，测试连接不再因普通文本回复而失败。
- 错误提示不再直接暴露 `Expecting value`，显示可诊断原因。
