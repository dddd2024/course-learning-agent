# Tasks

按合并计划包组织任务，遵循 TDD（先写失败测试，再写最小实现）。每个模块完成后运行相关测试。依赖关系见末尾。

- [x] Task 1: 后端配置与加密基础设施（B2、B3）
  - [ ] SubTask 1.1: core/config.py 新增 LLM_BASE_URL、LLM_MODEL、LLM_TIMEOUT_SECONDS、LLM_TEMPERATURE、LLM_MAX_TOKENS、LLM_CONFIG_SECRET_KEY 配置项
  - [ ] SubTask 1.2: backend/.env.example 补齐新配置项示例
  - [ ] SubTask 1.3: 编写 core/crypto.py 失败测试（encrypt/decrypt 可逆、密文不含明文）
  - [ ] SubTask 1.4: 实现 core/crypto.py（Fernet 对称加密，encrypt(api_key) -> 密文，decrypt(密文) -> 明文）
  - [ ] SubTask 1.5: requirements.txt 新增 cryptography
  - [ ] SubTask 1.6: 验证 crypto 测试通过

- [x] Task 2: UserLLMConfig 模型与 Schema（B1、B4）
  - [ ] SubTask 2.1: 编写 models/llm_config.py（UserLLMConfig 表：id, user_id, provider, name, base_url, model, api_key_encrypted, enabled, is_default, temperature, max_tokens, timeout_seconds, last_test_status, last_test_error, last_test_at）
  - [ ] SubTask 2.2: 注册到 models/__init__.py
  - [ ] SubTask 2.3: 编写 schemas/llm_config.py（Create、Update、Response（不含 api_key 明文，含 api_key_masked）、ListResponse、TestResponse、ActiveResponse）
  - [ ] SubTask 2.4: 编写模型测试（建表成功、字段完整）

- [x] Task 3: LLM 配置服务层与接口（B5）
  - [ ] SubTask 3.1: 编写 services/llm_config_service.py 失败测试（create 加密、get_active 返回启用配置、enable 互斥、test_connection 调用真实 API）
  - [ ] SubTask 3.2: 实现 services/llm_config_service.py（get_active_config、create_config、update_config、delete_config、enable_config、test_connection）
  - [ ] SubTask 3.3: 编写 api/v1/endpoints/llm_configs.py 失败测试（CRUD/enable/active/test，user_id 隔离，越权 404，响应不含明文 key）
  - [ ] SubTask 3.4: 实现 api/v1/endpoints/llm_configs.py（GET/POST /llm-configs、GET /llm-configs/active、PUT/DELETE /llm-configs/{id}、POST /llm-configs/{id}/enable、POST /llm-configs/{id}/test）
  - [ ] SubTask 3.5: 注册 router 到 api/v1/api.py
  - [ ] SubTask 3.6: 验证全部 LLM 配置测试通过

- [x] Task 4: 真实 LLM 调用层（B6）
  - [ ] SubTask 4.1: 编写 agents/llm.py 真实调用失败测试（mock httpx，验证请求体、response_format、JSON 解析、重试逻辑）
  - [ ] SubTask 4.2: 实现 _real_response：POST {base_url}/chat/completions，带 Bearer api_key，response_format={type:json_object}，400 时移除重试
  - [ ] SubTask 4.3: call_llm 增加可选 user_config 参数（dict with provider/base_url/model/api_key/temperature/max_tokens/timeout）
  - [ ] SubTask 4.4: 实现三层 fallback：user_config > settings.LLM_PROVIDER=real > mock；real 调用失败回退 mock
  - [ ] SubTask 4.5: 验证 LLM 调用测试通过

- [x] Task 5: Agent 层与 endpoints 接入用户配置（B7）
  - [ ] SubTask 5.1: 改造 course_qa.py/outline.py/planner.py/quiz.py，answer 函数接收可选 user_config 参数，传递给 call_llm
  - [ ] SubTask 5.2: 改造 chat.py endpoint，调用 Agent 前读取 current_user active config，传入 Agent
  - [ ] SubTask 5.3: 改造 knowledge_points.py、plans.py、quizzes.py endpoint，同样读取 active config 传入 Agent
  - [ ] SubTask 5.4: 编写集成测试（有 user_config 时 Agent 使用用户配置，无配置时回退 mock）
  - [ ] SubTask 5.5: 验证现有 chat/knowledge/plans/quizzes 测试不回归

- [x] Task 6: AgentAudit 增强（B8）
  - [ ] SubTask 6.1: 修改 models/audit.py，AgentRun 新增 provider、config_id 字段
  - [ ] SubTask 6.2: 修改 agents/audit.py create_run，接收 provider、config_id 参数
  - [ ] SubTask 6.3: 修改 schemas/audit.py，AgentRunResponse 新增 provider、config_id
  - [ ] SubTask 6.4: 修改 chat.py/knowledge_points.py/plans.py/quizzes.py，create_run 时传入 provider、config_id
  - [ ] SubTask 6.5: 编写测试验证审计记录含 provider、config_id，不含 api_key
  - [ ] SubTask 6.6: 验证审计测试通过

- [x] Task 7: 资料解析补全（md + pptx）
  - [ ] SubTask 7.1: 编写 parse_md/parse_pptx 失败测试
  - [ ] SubTask 7.2: 实现 parse_md（按文本读取）、parse_pptx（python-pptx 提取每页文本框，page_no=slide_index+1）
  - [ ] SubTask 7.3: 修改 parse_file 分发，支持 md/pptx
  - [ ] SubTask 7.4: requirements.txt 新增 python-pptx
  - [ ] SubTask 7.5: 验证解析测试通过，现有 parse 测试不回归

- [x] Task 8: 前端个人中心页面（F1-F7）
  - [ ] SubTask 8.1: 创建 frontend/src/api/llmConfig.ts（list/create/update/delete/enable/test/active 封装）
  - [ ] SubTask 8.2: 创建 frontend/src/views/ProfileView.vue（用户信息卡片 + 配置列表 + 新增/编辑弹窗 + 启用 + 测试连接，API Key 只显示 masked）
  - [ ] SubTask 8.3: 修改 router/index.ts 新增 /profile 路由
  - [ ] SubTask 8.4: 修改 MainLayout.vue 侧边栏新增"个人中心"菜单
  - [ ] SubTask 8.5: npm run build 验证通过

- [x] Task 9: CI 与文档（Q7、Q8）
  - [ ] SubTask 9.1: 创建 .github/workflows/ci.yml（push 触发：backend pytest + frontend npm build）
  - [ ] SubTask 9.2: 更新 README.md，新增 mock/real/用户配置三层策略说明、个人中心使用说明、pptx/md 解析说明
  - [ ] SubTask 9.3: 更新 backend/.env.example 完整配置示例
  - [ ] SubTask 9.4: 验证 CI yaml 语法正确

- [x] Task 10: 联调与验收
  - [ ] SubTask 10.1: 运行后端全量测试，确认无回归
  - [ ] SubTask 10.2: 运行前端 npm run build，确认无类型错误
  - [ ] SubTask 10.3: 越权测试（用户 A 无法访问用户 B 的 llm-configs）
  - [ ] SubTask 10.4: 验收清单核对（checklist.md）
  - [ ] SubTask 10.5: 提交并推送到 GitHub

# Task Dependencies
- Task 2 依赖 Task 1（需要 crypto）
- Task 3 依赖 Task 1、Task 2
- Task 4 依赖 Task 1（需要 config）
- Task 5 依赖 Task 3、Task 4
- Task 6 依赖 Task 5
- Task 7 无依赖，可与 Task 2-6 并行
- Task 8 依赖 Task 3（需要后端接口）
- Task 9 依赖 Task 1-8
- Task 10 依赖 Task 1-9
