# 课程学习助手 Agent 平台 Spec

## Why
大学生在多门课程学习中存在资料分散、重点内容难以快速查找、学习计划不清晰、作业与复习任务容易遗漏等问题。本系统以课程资料为中心、以 Agent 为执行层、以学习计划和待办任务为闭环，把分散资料转化为可检索、可引用、可计划、可追踪的学习资产。

## What Changes
- 搭建前后端分离工程骨架：FastAPI 后端 + Vue/Vite/TS 前端
- 实现用户认证（注册/登录/JWT）与基于 user_id 的数据隔离
- 实现课程 CRUD 管理
- 实现资料上传、解析（TXT/PDF/DOCX）、切块与关键词检索
- 实现 RAG 课程问答 Agent（CourseQAAgent），输出结构化 JSON 并绑定引用
- 实现资料来源引用（citations）展示与依据查看
- 实现知识点提取（OutlineAgent）与复习提纲
- 实现学习计划生成（PlannerAgent/TaskDecomposer）与待办管理
- 实现多课程学习规划（MultiCourseScheduler）
- 实现扩展亮点：检索过程可视化、Agent 执行审计、测验与薄弱点、学习进度可视化
- 提供 mock LLM/embedding 降级模式，保证无外部 API Key 也能演示

## Impact
- 新建前端项目：frontend/（Vue3 + Vite + TS + Element Plus + Pinia + Vue Router）
- 新建后端项目：backend/（FastAPI + SQLAlchemy + Pydantic + JWT）
- 新建存储目录：storage/（uploads、parsed、exports）
- 数据库：SQLite（course_assistant.db），包含 users、courses、materials、material_chunks、conversations、messages、citations、knowledge_points、study_goals、study_tasks、todos、agent_runs、agent_steps、quizzes、quiz_items、weak_points 等表
- Agent 层：backend/app/agents/（Prompt 模板、LLM 适配层、各 Agent）
- 检索层：backend/app/retrieval/（解析、切块、检索、引用校验）

## ADDED Requirements

### Requirement: 项目骨架与基础设施
系统 SHALL 提供可一键启动的前后端分离工程骨架，包含配置、数据库连接、统一异常处理、CORS、健康检查接口。

#### Scenario: 健康检查
- **WHEN** 访问 GET /api/v1/health
- **THEN** 返回 200 和 {"status": "ok"}

#### Scenario: 数据库初始化
- **WHEN** 执行 python scripts/init_db.py
- **THEN** 创建 SQLite 数据库及全部数据表

### Requirement: 用户认证与权限隔离
系统 SHALL 提供用户名/密码注册登录，返回 JWT；除登录注册外所有接口必须携带 Bearer token；所有业务查询必须带 user_id 条件实现数据隔离。

#### Scenario: 注册与登录
- **WHEN** 用户注册 test01 并登录
- **THEN** 返回 access_token，可访问受保护接口

#### Scenario: 越权访问被拒绝
- **WHEN** 用户 A 请求用户 B 的课程 ID
- **THEN** 返回 403 或 404

### Requirement: 课程管理
系统 SHALL 提供课程的增删改查 API 与前端页面，课程是系统根实体，资料、对话、知识点、计划均关联课程。

#### Scenario: 课程 CRUD
- **WHEN** 创建"操作系统"课程，修改教师，删除
- **THEN** 列表同步变化，数据库一致

### Requirement: 资料上传与解析
系统 SHALL 支持上传 TXT/PDF/DOCX 文件，保存原始文件，异步/同步解析为文本并切块，写入 material_chunks；资料状态流转为 uploaded -> processing -> ready（失败为 failed）。

#### Scenario: 资料上传解析
- **WHEN** 上传 PDF/TXT，等待处理
- **THEN** materials.status=ready，chunks > 0

### Requirement: 资料检索
系统 SHALL 提供关键词检索（SQLite FTS/LIKE），支持按课程过滤；配置 embedding 时支持向量召回与混合重排；无 embedding 时降级为关键词检索模式并前端明确提示。

#### Scenario: 关键词检索
- **WHEN** 输入关键词搜索某课程资料
- **THEN** 返回相关 chunk 列表

### Requirement: RAG 课程问答（CourseQAAgent）
系统 SHALL 在课程对话中先检索课程资料片段，再调用 LLM 生成结构化 JSON 回答，包含 answer、key_points、citations、not_found、follow_up_questions；回答绑定 citations（chunk_id、quote_text、confidence）。

#### Scenario: 资料内提问
- **WHEN** 提问资料中存在的问题
- **THEN** 回答包含 citations，点击能查看原片段

#### Scenario: 无依据回答
- **WHEN** 提问资料外问题
- **THEN** not_found=true，提示未找到直接依据，不伪造引用

### Requirement: 知识点整理（OutlineAgent）
系统 SHALL 从课程资料 chunks 提取知识点，按"章节-知识点-子知识点-考法/任务"四层整理，保存到 knowledge_points 表并生成复习提纲。

#### Scenario: 知识点提取
- **WHEN** 点击生成知识点
- **THEN** 生成树形知识点，包含来源片段

### Requirement: 学习计划与任务拆解（PlannerAgent）
系统 SHALL 接收目标、截止日期、每日可用时间，输出可落库的阶段任务 JSON（含课程、任务类型、预计分钟、优先级、完成标准），并由调度算法生成每日 todos。

#### Scenario: 单课程计划
- **WHEN** 输入 7 天复习目标
- **THEN** 生成 study_goal、study_tasks、todos

### Requirement: 多课程学习规划
系统 SHALL 综合多课程截止日期、任务量、每日可用时间和优先级（priority_score = deadline_urgency*0.45 + workload_weight*0.30 + weak_point_weight*0.15 + user_priority*0.10）生成跨课程综合日程；每日任务不超 available_minutes，单课程连续不超 90 分钟。

#### Scenario: 多课程计划
- **WHEN** 选择两门课程和不同截止日期
- **THEN** 输出按日期排列的综合计划

### Requirement: 待办管理
系统 SHALL 提供待办列表（按日期、状态、课程筛选）、完成/延期/删除操作；延期时提示是否重排后续任务。

#### Scenario: 完成待办
- **WHEN** 完成今日任务
- **THEN** 状态变 completed，进度图更新

### Requirement: Agent 执行审计
系统 SHALL 为每次 Agent 调用创建 agent_runs 记录，检索/重排/生成/校验等步骤写入 agent_steps，记录输入、输出、Prompt 版本、模型名称、耗时、错误信息；前端可查看运行列表与步骤详情。

#### Scenario: Agent 审计
- **WHEN** 查看最近一次问答 run
- **THEN** 能看到检索、生成、校验步骤

### Requirement: 测验与薄弱点
系统 SHALL 根据知识点生成测验题（QuizAgent），提交后判分，错题对应知识点写入 weak_points 并提升优先级；下一次计划生成时增加薄弱点复习任务。

#### Scenario: 测验与薄弱点
- **WHEN** 生成测验并答错一题
- **THEN** 记录错题，weak_points 更新

### Requirement: LLM 适配层与 mock 模式
系统 SHALL 封装 call_llm(prompt, schema) 适配层，支持真实 API 和 mock 模式；无 API Key 时 mock 模式可完整演示全部 Agent 功能。

#### Scenario: mock 模式演示
- **WHEN** LLM_PROVIDER=mock
- **THEN** Agent 仍返回结构化 JSON，可演示问答/计划/知识点

### Requirement: 前端页面与交互
系统 SHALL 提供登录注册、仪表盘、课程管理、课程详情、资料库、Agent 对话、知识点、学习计划、多课程规划、待办、测验、审计等页面；课程详情页形成"资料-问答-知识点-计划"闭环；对话回答下方必须有引用卡片。

#### Scenario: 对话引用展示
- **WHEN** 在对话页提问
- **THEN** 回答下方显示引用卡片（资料名、页码、片段摘要、相关度），点击打开依据抽屉

### Requirement: 测试与验收
系统 SHALL 提供单元测试（pytest，核心函数通过率 90%+）、接口测试（主要接口 2xx/4xx 符合预期）、前端可演示路径无阻塞错误、Agent 输出 JSON 可解析且引用可追溯。

#### Scenario: 越权测试
- **WHEN** 构造用户 A 请求用户 B 课程
- **THEN** 返回 403 或 404
