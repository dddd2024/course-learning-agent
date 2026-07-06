# Checklist

## 基础设施
- [x] GET /api/v1/health 返回 {"status": "ok"}
- [x] scripts/init_db.py 可创建全部数据表
- [x] backend/requirements.txt 包含所需依赖
- [x] CORS 正确配置，前端可调用后端

## 用户认证与权限
- [x] 注册接口校验用户名唯一、密码长度
- [x] 登录接口返回 access_token
- [x] 受保护接口需要 Bearer token
- [x] 课程/资料/任务查询带 user_id
- [x] 用户 A 不能访问用户 B 的课程（返回 403/404）
- [x] 密码哈希存储，非明文

## 课程管理
- [x] 课程 CRUD API 可用
- [x] 课程列表支持分页与关键词
- [x] 前端课程列表/创建/编辑/删除可操作（代码层面已验证，需手动确认）

## 资料管理
- [x] 上传接口校验文件类型和大小
- [x] 原始文件保存到 storage/uploads
- [x] materials.status 流转 uploaded -> processing -> ready
- [x] 解析失败 status=failed 并记录 error_message
- [x] TXT/PDF/DOCX 至少两类解析成功
- [x] 上传后 chunks > 0
- [x] 切块长度 500-800 中文字，重叠 80-120
- [x] 前端资料上传页与状态轮询可用（代码层面已验证，需手动确认）
- [x] 前端资料检索框可用（代码层面已验证，需手动确认）

## 检索
- [x] keyword_search 返回相关 chunk
- [x] 检索支持按 course_id 过滤
- [x] 无 embedding 时降级为关键词检索模式
- [x] 前端在关键词模式下明确提示（代码层面已验证，需手动确认）

## 课程问答
- [x] CourseQAAgent 先检索后生成
- [x] answer_json 包含 answer、key_points、citations、not_found、follow_up_questions
- [x] 资料内提问返回 citations
- [x] 资料外提问 not_found=true，不伪造引用
- [x] POST /chat 接口可用
- [x] conversations/messages 保存问答记录
- [x] 前端对话页可提问、显示加载/错误状态（代码层面已验证，需手动确认）

## 引用
- [x] citations 表绑定 message_id 与 chunk_id
- [x] CitationVerifier 剔除非法引用
- [x] 引用包含 quote_text 与 confidence
- [x] GET /messages/{id}/citations 可查询
- [x] 前端引用卡片展示资料名、页码、片段摘要、相关度（代码层面已验证，需手动确认）
- [x] 点击卡片打开依据抽屉显示完整片段（代码层面已验证，需手动确认）

## 知识点
- [x] OutlineAgent 生成树形知识点
- [x] knowledge_points 含来源片段
- [x] importance 计算正确
- [x] 前端知识点页可生成并查看提纲（代码层面已验证，需手动确认）

## 学习计划
- [x] PlannerAgent 输出可落库任务 JSON
- [x] 生成 study_goal、study_tasks、todos
- [x] 调度算法按 priority_score 排序
- [x] POST /plans 接口可用
- [x] 前端计划页可生成计划与待办（代码层面已验证，需手动确认）

## 多课程规划
- [x] MultiCourseScheduler 综合截止/任务量/可用时间
- [x] priority_score 计算正确
- [x] 每日任务不超 available_minutes
- [x] 单课程连续不超 90 分钟
- [x] POST /plans/multi 接口可用
- [x] 前端多课程规划页可用（代码层面已验证，需手动确认）

## 待办
- [x] GET /todos 支持日期、状态、课程筛选
- [x] PATCH /todos/{id} 可完成/延期
- [x] 前端待办页可操作（代码层面已验证，需手动确认）

## Agent 审计
- [x] agent_runs 记录每次 Agent 调用
- [x] agent_steps 记录检索/生成/校验步骤
- [x] 记录 Prompt 版本、模型、耗时、错误
- [x] GET /agent-runs 与详情接口可用
- [x] 前端审计页可展示运行列表与步骤（代码层面已验证，需手动确认）

## 测验与薄弱点
- [x] QuizAgent 生成题目
- [x] 提交后判分并显示解析
- [x] 错题写入 weak_points
- [x] 计划生成时增加薄弱点复习任务
- [x] 前端测验页与薄弱点卡片可用（代码层面已验证，需手动确认）

## LLM 适配与降级
- [x] call_llm 适配层支持真实 API 与 mock
- [x] LLM_PROVIDER=mock 时全部 Agent 可演示
- [x] Prompt 文件版本化管理

## 检索可视化与可靠性
- [x] 依据抽屉展示 Top-K 命中片段与分数
- [x] 无引用时显示提示
- [x] 回答可靠性等级（高/中/低/失败）正确显示

## 测试与验收
- [x] pytest 核心函数通过率 90%+
- [x] 主要接口 2xx/4xx 符合预期
- [x] TC-01 至 TC-12 用例通过
- [x] 越权访问测试通过
- [x] mock 模式全流程可演示
- [x] demo 账号 demo/demo123456 可用
- [x] scripts/seed_demo_data.py 可初始化演示数据
- [x] scripts/run_dev.ps1 一键启动
- [x] README.md 启动说明完整
