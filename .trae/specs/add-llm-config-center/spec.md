# 用户级大模型配置中心 Spec

## Why
当前系统的 LLM 调用仅支持全局 `.env` 配置或 mock 模式，无法让每个用户使用自己的 OpenAI-compatible 大模型服务；个人中心页面缺失，不满足课程题目基础功能要求；资料上传允许 pptx/md 但解析器只支持 txt/pdf/docx，演示时上传 PPT 会失败；Agent 审计未记录实际模型配置，难以说明"哪个模型产生了回答"。本计划包做"收口型增强"，把系统从 mock 演示状态推进到可配置真实模型、可多人使用、可审计、可复现的状态。

## What Changes
- 新增用户级 LLM 配置中心（UserLLMConfig 表 + 加密存储 + CRUD/enable/active/test 接口）
- 实现 OpenAI-compatible 真实 LLM 调用层（支持 JSON 输出、response_format 兼容重试、错误处理）
- 改造 Agent 层与 endpoints，使其优先使用当前用户启用的配置（三层 fallback：用户配置 > 系统 real > mock）
- AgentAudit 增强：记录 provider/model/config_id，禁止记录 API Key
- 新增前端"个人中心"页面（ProfileView），含用户信息卡片 + 模型配置列表/新增/编辑/删除/启用/测试连接，API Key 只显示 masked
- 修复资料类型不一致：补 md 和 pptx 解析器
- 新增 GitHub Actions CI（pytest + npm build）
- 更新 README 说明 mock/real/用户配置三层策略

## Impact
- 新建表：user_llm_configs
- 修改表：agent_runs（新增 provider/config_id 字段）
- 新增后端文件：models/llm_config.py、core/crypto.py、schemas/llm_config.py、api/v1/endpoints/llm_configs.py、services/llm_config_service.py
- 修改后端文件：core/config.py、agents/llm.py、agents/audit.py、agents/course_qa.py、agents/outline.py、agents/planner.py、agents/quiz.py、api/v1/endpoints/chat.py、knowledge_points.py、plans.py、quizzes.py、api/v1/api.py、retrieval/parsers.py、models/__init__.py、models/audit.py
- 新增前端文件：src/api/llmConfig.ts、src/views/ProfileView.vue
- 修改前端文件：src/router/index.ts、src/layouts/MainLayout.vue
- 新增 CI：.github/workflows/ci.yml
- 更新：README.md、backend/.env.example、requirements.txt（新增 python-pptx、cryptography）

## ADDED Requirements

### Requirement: 用户级大模型配置管理
系统 SHALL 提供用户级 LLM 配置中心，每个用户可新增多个 OpenAI-compatible 配置（provider、name、base_url、model、api_key、temperature、max_tokens、timeout_seconds），启用其中一个，测试连接；API Key 必须加密入库，响应只返回 masked。

#### Scenario: 新增配置
- **WHEN** 用户 POST /api/v1/llm-configs 提交配置
- **THEN** 创建配置，api_key 加密存储，响应不返回明文

#### Scenario: 启用配置
- **WHEN** 用户 POST /api/v1/llm-configs/{id}/enable
- **THEN** 该配置 is_default=true，同用户其他配置 is_default=false

#### Scenario: 测试连接
- **WHEN** 用户 POST /api/v1/llm-configs/{id}/test
- **THEN** 调用真实 API 验证，返回 success/failed + 错误原因（不含 API Key），不修改启用状态

#### Scenario: 越权访问
- **WHEN** 用户 A 访问用户 B 的配置
- **THEN** 返回 404

### Requirement: 真实 OpenAI-compatible LLM 调用
系统 SHALL 实现真实 LLM 调用层，支持 /chat/completions 接口、JSON 输出、response_format 兼容重试（不支持时移除重试）；调用失败时回退 mock 保证演示不中断。

#### Scenario: 用户配置优先
- **WHEN** 用户启用了自己的 LLM 配置并提问
- **THEN** Agent 使用用户配置的 base_url/model/api_key 调用真实 API

#### Scenario: 三层 fallback
- **WHEN** 用户无配置、系统 LLM_PROVIDER=mock
- **THEN** Agent 回退 mock 模式返回结构化 JSON

### Requirement: Agent 审计增强
系统 SHALL 在 agent_runs 记录 provider/model/config_id，不记录 API Key。

#### Scenario: 审计记录模型
- **WHEN** 用户提问后查看 agent_runs
- **THEN** 能看到 provider、model、config_id 字段

### Requirement: 个人中心页面
系统 SHALL 提供 /profile 页面，含用户信息卡片和大模型配置管理卡片。

#### Scenario: 个人中心
- **WHEN** 用户点击侧边栏"个人中心"
- **THEN** 显示用户名、当前启用模型摘要、配置列表、新增/编辑/删除/启用/测试按钮

### Requirement: 资料解析补全
系统 SHALL 支持 txt/pdf/docx/md/pptx 五类文件解析，上传列表、解析接口、README 保持一致。

#### Scenario: 上传 PPT
- **WHEN** 用户上传 .pptx 文件
- **THEN** 解析成功，chunks > 0，page_no 对应 slide_index+1

#### Scenario: 上传 MD
- **WHEN** 用户上传 .md 文件
- **THEN** 按文本解析成功

## MODIFIED Requirements

### Requirement: LLM 适配层与 mock 模式
原系统仅支持全局 .env 配置。现修改为三层调用策略：用户配置优先 > 系统 real > mock 兜底。call_llm 接收可选 user_config 参数。

## REMOVED Requirements
无
