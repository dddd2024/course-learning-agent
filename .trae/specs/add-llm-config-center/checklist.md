# Checklist

## 配置与加密
- [x] core/config.py 新增 LLM_BASE_URL、LLM_MODEL、LLM_TIMEOUT_SECONDS、LLM_TEMPERATURE、LLM_MAX_TOKENS、LLM_CONFIG_SECRET_KEY
- [x] backend/.env.example 包含全部新配置项
- [x] core/crypto.py encrypt/decrypt 可逆，密文不含明文
- [x] requirements.txt 新增 cryptography、python-pptx

## UserLLMConfig 模型
- [x] user_llm_configs 表含全部字段（provider、name、base_url、model、api_key_encrypted、enabled、is_default、temperature、max_tokens、timeout_seconds、last_test_status、last_test_error、last_test_at）
- [x] init_db 后能建 user_llm_configs 表
- [x] schemas/llm_config.py 类型完整（Create/Update/Response/List/TestResponse/ActiveResponse）
- [x] Response 不返回 api_key 明文，返回 api_key_masked

## LLM 配置接口
- [x] GET /api/v1/llm-configs 列出当前用户配置
- [x] POST /api/v1/llm-configs 新增配置（api_key 加密入库）
- [x] GET /api/v1/llm-configs/active 返回当前启用配置
- [x] PUT /api/v1/llm-configs/{id} 更新配置
- [x] DELETE /api/v1/llm-configs/{id} 删除配置
- [x] POST /api/v1/llm-configs/{id}/enable 启用配置（互斥）
- [x] POST /api/v1/llm-configs/{id}/test 测试连接（不修改启用状态）
- [x] 所有接口按 user_id 隔离，越权返回 404
- [x] 响应不含 api_key 明文

## 真实 LLM 调用
- [x] _real_response 实现 OpenAI-compatible /chat/completions
- [x] 支持 response_format={type:json_object}
- [x] 400 时移除 response_format 重试
- [x] call_llm 接收可选 user_config 参数
- [x] 三层 fallback：user_config > system real > mock
- [x] real 调用失败回退 mock

## Agent 集成
- [x] CourseQAAgent/OutlineAgent/PlannerAgent/QuizAgent 接收 user_config
- [x] chat/knowledge_points/plans/quizzes endpoint 读取 active config 传入 Agent
- [x] 有 user_config 时使用用户配置
- [x] 无配置时回退 mock

## Agent 审计增强
- [x] agent_runs 新增 provider、config_id 字段
- [x] AgentAudit.create_run 接收 provider、config_id
- [x] 审计记录含 provider、model、config_id
- [x] 审计不记录 api_key

## 资料解析补全
- [x] parse_md 按文本读取
- [x] parse_pptx 提取每页文本框，page_no=slide_index+1
- [x] parse_file 支持 txt/pdf/docx/md/pptx
- [x] 上传 pptx 解析成功，chunks > 0
- [x] 上传 md 解析成功

## 前端个人中心
- [x] frontend/src/api/llmConfig.ts 封装全部接口
- [x] ProfileView.vue 含用户信息卡片
- [x] ProfileView.vue 含配置列表（名称、provider、base_url、model、api_key 掩码、启用状态、测试状态、操作）
- [x] 新增/编辑弹窗含全部字段
- [x] API Key 只显示 masked，编辑不回显明文
- [x] 测试连接成功/失败有明确提示
- [x] /profile 路由需要登录
- [x] 侧边栏出现"个人中心"菜单
- [x] npm run build 通过

## CI 与文档
- [x] .github/workflows/ci.yml push 触发
- [x] CI 运行 backend pytest
- [x] CI 运行 frontend npm build
- [x] README 更新三层策略说明
- [x] README 更新个人中心使用说明
- [x] README 更新 pptx/md 解析说明

## 测试与验收
- [x] 后端全量测试通过（含新增 test_llm_configs、test_crypto、test_parsers_md_pptx）
- [x] 前端 npm run build 通过
- [x] 越权测试：用户 A 无法访问用户 B 的 llm-configs
- [x] 加密测试：api_key 入库非明文，响应非明文
- [x] 三层 fallback 测试：用户配置 > 系统 > mock
- [x] 审计测试：agent_runs 含 provider/config_id，不含 api_key
- [x] 解析测试：pptx/md 解析成功
