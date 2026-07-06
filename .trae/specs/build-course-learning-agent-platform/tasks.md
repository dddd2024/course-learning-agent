# Tasks

按设计文档 12 天冲刺计划组织任务，遵循 TDD（先写失败测试，再写最小实现）。每个模块完成后运行相关测试。

- [x] Task 1: 项目骨架与基础设施（BE-01）
  - [ ] SubTask 1.1: 创建 backend/ FastAPI 项目结构（app/main.py、api、core、models、schemas、services、agents、retrieval、tests 目录）
  - [ ] SubTask 1.2: 配置管理（app/core/config.py，读取 DATABASE_URL、JWT_SECRET_KEY、UPLOAD_DIR、LLM_PROVIDER 等环境变量）
  - [ ] SubTask 1.3: 数据库连接（app/core/database.py，SQLAlchemy engine/session）
  - [ ] SubTask 1.4: 统一异常处理与 CORS 中间件
  - [ ] SubTask 1.5: GET /api/v1/health 健康检查接口
  - [ ] SubTask 1.6: requirements.txt（fastapi、uvicorn、sqlalchemy、pydantic、python-jose、passlib、python-multipart、pypdf、python-docx 等）
  - [ ] SubTask 1.7: scripts/init_db.py 数据库初始化脚本
  - [ ] SubTask 1.8: 编写健康检查与配置测试

- [x] Task 2: 用户认证模块（BE-02）
  - [ ] SubTask 2.1: 编写注册接口失败测试（重复用户名返回错误）
  - [ ] SubTask 2.2: users 表 ORM 模型 + Pydantic schema
  - [ ] SubTask 2.3: 密码哈希（passlib bcrypt）
  - [ ] SubTask 2.4: POST /auth/register 注册接口实现
  - [ ] SubTask 2.5: POST /auth/login 登录接口实现（返回 access_token）
  - [ ] SubTask 2.6: JWT 验证依赖（get_current_user）
  - [ ] SubTask 2.7: 编写登录失败与受保护接口测试，验证通过

- [x] Task 3: 课程模块（BE-03）
  - [ ] SubTask 3.1: 编写课程 CRUD 失败测试（含越权访问返回 403/404）
  - [ ] SubTask 3.2: courses 表 ORM 模型（含 user_id 隔离字段）
  - [ ] SubTask 3.3: 课程 CRUD API（GET/POST/PUT/DELETE /courses）
  - [ ] SubTask 3.4: 所有查询带 user_id 条件实现数据隔离
  - [ ] SubTask 3.5: 编写课程 CRUD 与越权测试，验证通过

- [x] Task 4: 前端项目初始化（FE-01）
  - [ ] SubTask 4.1: 创建 Vue3 + Vite + TS 项目
  - [ ] SubTask 4.2: 安装 Element Plus、Pinia、Vue Router、Axios
  - [ ] SubTask 4.3: 配置路由表（/login、/dashboard、/courses 等）
  - [ ] SubTask 4.4: 主布局组件与 axios 拦截器（携带 token）
  - [ ] SubTask 4.5: 验证能进入首页框架

- [x] Task 5: 前端登录注册与课程管理（FE-02、FE-03）
  - [ ] SubTask 5.1: 登录注册页（表单、错误提示）
  - [ ] SubTask 5.2: token 保存到 localStorage + Pinia，路由守卫
  - [ ] SubTask 5.3: 课程列表页与创建/编辑弹窗、删除确认
  - [ ] SubTask 5.4: 验证登录后进入仪表盘、课程 CRUD 可操作

- [x] Task 6: 资料上传与存储（BE-04）
  - [ ] SubTask 6.1: 编写上传接口失败测试（非法类型被拒绝）
  - [ ] SubTask 6.2: materials 表 ORM 模型（含 status、file_path、version）
  - [ ] SubTask 6.3: 文件类型与大小校验
  - [ ] SubTask 6.4: 保存原始文件到 storage/uploads/{user_id}/{course_id}/{material_id}/
  - [ ] SubTask 6.5: POST /courses/{id}/materials 上传接口，创建 materials 记录 status=uploaded
  - [ ] SubTask 6.6: GET /courses/{id}/materials 资料列表接口
  - [ ] SubTask 6.7: 编写上传与列表测试，验证通过

- [x] Task 7: 资料解析与切块（BE-05）
  - [ ] SubTask 7.1: 编写解析失败测试（上传后 chunks > 0）
  - [ ] SubTask 7.2: material_chunks 表 ORM 模型（material_id、course_id、chunk_index、page_no、text、keyword_text）
  - [ ] SubTask 7.3: TXT/PDF/DOCX 解析器（至少两类，pypdf、python-docx）
  - [ ] SubTask 7.4: 切块策略（500-800 中文字，重叠 80-120，优先按标题/章节切分）
  - [ ] SubTask 7.5: POST /materials/{id}/parse 触发解析接口
  - SubTask 7.6: 状态流转 uploaded -> processing -> ready（失败 failed + error_message）
  - [ ] SubTask 7.7: GET /materials/{id}/chunks 查看片段接口
  - [ ] SubTask 7.8: 编写解析与切块测试，验证通过

- [x] Task 8: 检索模块（BE-06）
  - [ ] SubTask 8.1: 编写检索失败测试（关键词返回相关 chunk）
  - [ ] SubTask 8.2: keyword_search(course_id, query, top_k) 实现（SQLite LIKE/FTS）
  - [ ] SubTask 8.3: GET /search 资料检索接口（按 course_id 过滤）
  - [ ] SubTask 8.4: 向量召回与混合重排预留接口（embedding 可选，无则降级）
  - [ ] SubTask 8.5: 编写检索测试，验证通过

- [x] Task 9: 前端资料管理页（FE-04）
  - [ ] SubTask 9.1: 上传组件（文件选择、进度）
  - [ ] SubTask 9.2: 资料表格与状态显示（轮询 status）
  - [ ] SubTask 9.3: 资料检索框与片段展示
  - [ ] SubTask 9.4: 验证资料上传和检索可演示

- [x] Task 10: LLM 适配层与 Prompt 模板（AG-01、AG-02）
  - [ ] SubTask 10.1: 编写 call_llm 失败测试（mock 模式返回结构化 JSON）
  - [ ] SubTask 10.2: prompts/ 目录与版本化 Prompt 文件（course_qa_v1.md 等）
  - [ ] SubTask 10.3: call_llm(prompt, schema) 适配层，支持真实 API 与 mock 模式
  - [ ] SubTask 10.4: mock 模式实现（按 schema 返回合法 JSON）
  - [ ] SubTask 10.5: 编写 LLM 适配层测试，验证通过

- [x] Task 11: 对话模块与 CourseQAAgent（BE-07、AG-03）
  - [ ] SubTask 11.1: 编写问答失败测试（资料内提问返回 citations，资料外 not_found=true）
  - [ ] SubTask 11.2: conversations 与 messages 表 ORM 模型
  - [ ] SubTask 11.3: POST /conversations、GET /conversations 接口
  - [ ] SubTask 11.4: CourseQAAgent 实现（检索 + LLM + 结构化输出 + 引用绑定）
  - [ ] SubTask 11.5: answer_json Schema 校验（answer、key_points、citations、not_found、follow_up_questions）
  - [ ] SubTask 11.6: POST /chat 课程问答接口
  - [ ] SubTask 11.7: 编写问答与引用测试，验证通过

- [x] Task 12: 引用模块与 CitationVerifier（BE-08、AG-04）
  - [ ] SubTask 12.1: 编写引用校验失败测试（非法引用被剔除）
  - [ ] SubTask 12.2: citations 表 ORM 模型
  - [ ] SubTask 12.3: CitationVerifier 实现（检查 chunk_id 是否来自检索结果）
  - [ ] SubTask 12.4: GET /messages/{id}/citations 引用查询接口
  - [ ] SubTask 12.5: 编写引用校验测试，验证通过

- [x] Task 13: 前端对话页与引用展示（FE-05、FE-06）
  - [ ] SubTask 13.1: 消息列表、输入框、加载/错误状态
  - [ ] SubTask 13.2: 引用卡片（资料名、页码、片段摘要、相关度）
  - [ ] SubTask 13.3: 依据查看抽屉（完整片段 + 检索过程）
  - [ ] SubTask 13.4: 验证可向课程 Agent 提问并查看引用来源

- [x] Task 14: 知识点模块与 OutlineAgent（BE-09、AG-05）
  - [ ] SubTask 14.1: 编写知识点提取失败测试（生成树形知识点含来源片段）
  - [ ] SubTask 14.2: knowledge_points 表 ORM 模型（title、summary、importance、source_chunk_ids、exam_style、review_action）
  - [ ] SubTask 14.3: OutlineAgent 实现（四层整理 + importance 计算）
  - [ ] SubTask 14.4: POST /courses/{id}/knowledge-points/generate、GET /courses/{id}/knowledge-points 接口
  - [ ] SubTask 14.5: 前端知识点页（树形展示、复习提纲、生成按钮）FE-07
  - [ ] SubTask 14.6: 编写知识点测试，验证通过

- [x] Task 15: 学习计划与待办模块（BE-10、AG-06）
  - [ ] SubTask 15.1: 编写计划生成失败测试（生成 goal/tasks/todos）
  - [ ] SubTask 15.2: study_goals、study_tasks、todos 表 ORM 模型
  - [ ] SubTask 15.3: PlannerAgent 与 TaskDecomposer 实现（输出可落库任务 JSON）
  - [ ] SubTask 15.4: 计划调度算法（按 priority_score 排序，逐日填充）
  - [ ] SubTask 15.5: POST /plans、GET /todos、PATCH /todos/{id} 接口
  - [ ] SubTask 15.6: 前端学习计划页（目标表单、计划列表、日历/看板）FE-08
  - [ ] SubTask 15.7: 前端待办页（今日/全部、状态筛选、完成/延期）FE-08
  - [ ] SubTask 15.8: 编写计划与待办测试，验证通过

- [x] Task 16: 多课程规划（BE-11、AG-06）
  - [ ] SubTask 16.1: 编写多课程规划失败测试（输出按日期排列综合计划）
  - [ ] SubTask 16.2: MultiCourseScheduler 实现（priority_score 计算 + 每日容量限制 + 单课程 90 分钟拆分）
  - [ ] SubTask 16.3: POST /plans/multi 接口
  - [ ] SubTask 16.4: 前端多课程规划页（课程选择、截止日期、可用时间、结果表）FE-09
  - [ ] SubTask 16.5: 编写多课程规划测试，验证通过

- [x] Task 17: Agent 审计与统计（BE-12、AG-08）
  - [x] SubTask 17.1: 编写审计失败测试（可查看 Agent 执行链）
  - [x] SubTask 17.2: agent_runs、agent_steps 表 ORM 模型
  - [x] SubTask 17.3: AgentAudit 工具（记录输入、输出、步骤、耗时、错误）
  - [x] SubTask 17.4: 在 CourseQAAgent/OutlineAgent/PlannerAgent 中接入审计
  - [x] SubTask 17.5: GET /agent-runs、GET /agent-runs/{id} 接口
  - [x] SubTask 17.6: 前端审计页（运行列表、步骤详情、进度图）FE-10
  - [x] SubTask 17.7: 编写审计测试，验证通过

- [x] Task 18: 测验与薄弱点（AG-07）— 后端完成，前端测验页待做
  - [x] SubTask 18.1: 编写测验失败测试（生成题目 + 提交判分 + 薄弱点更新）
  - [x] SubTask 18.2: quizzes、quiz_items、weak_points 表 ORM 模型
  - [x] SubTask 18.3: QuizAgent 实现（按知识点生成题目）
  - [x] SubTask 18.4: POST /quizzes、POST /quizzes/{id}/submit 接口
  - [x] SubTask 18.5: 错题对应 knowledge_point_id 写入 weak_points，计划生成时增加复习任务
  - [x] SubTask 18.6: 前端测验页（题目、解析、得分、错题）与薄弱点卡片
  - [x] SubTask 18.7: 编写测验与薄弱点测试，验证通过

- [x] Task 19: 检索过程可视化
  - [x] SubTask 19.1: 后端记录 retrieve/rerank 步骤（query、filters、top_k、chunk_id、score）
  - [x] SubTask 19.2: 前端依据抽屉展示 Top-K 命中片段、分数、是否被引用
  - [x] SubTask 19.3: 无引用时显示"未找到可靠资料依据"

- [x] Task 20: 回答可靠性等级
  - [x] SubTask 20.1: 实现可靠性等级计算（高/中/低/失败）
  - [x] SubTask 20.2: 前端按等级提示

- [x] Task 21: 演示数据与启动脚本
  - [x] SubTask 21.1: scripts/seed_demo_data.py（demo 账号、样例课程、样例资料）
  - [x] SubTask 21.2: scripts/run_dev.ps1 一键启动脚本
  - [x] SubTask 21.3: README.md 启动说明
  - [x] SubTask 21.4: .env.example 环境变量示例

- [x] Task 22: 联调与测试报告
  - [x] SubTask 22.1: 执行核心测试用例 TC-01 至 TC-12
  - [x] SubTask 22.2: 越权访问测试
  - [x] SubTask 22.3: mock 模式全流程演示验证
  - [x] SubTask 22.4: 修复联调问题

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 2
- Task 4 无依赖，可与 Task 2/3 并行
- Task 5 依赖 Task 4 与 Task 3
- Task 6 依赖 Task 3
- Task 7 依赖 Task 6
- Task 8 依赖 Task 7
- Task 9 依赖 Task 8 与 Task 4
- Task 10 依赖 Task 1
- Task 11 依赖 Task 8 与 Task 10
- Task 12 依赖 Task 11
- Task 13 依赖 Task 12 与 Task 4
- Task 14 依赖 Task 8 与 Task 10
- Task 15 依赖 Task 14
- Task 16 依赖 Task 15
- Task 17 依赖 Task 11
- Task 18 依赖 Task 14
- Task 19 依赖 Task 12 与 Task 17
- Task 20 依赖 Task 12
- Task 21 依赖全部核心任务
- Task 22 依赖全部任务
