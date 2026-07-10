# 第一轮执行结果

## 基线

- 起始分支：`main`
- 执行范围：计划文档第 19 节第一轮优先闭环

## 已实施

- SEC-01：移除公开 `/uploads` 静态挂载；原始资料和图片改由鉴权接口读取，且服务端解析路径后验证其仍在上传根目录内。
- DATA-01 / DATA-04：SQLite 连接启用外键；课程删除在单个数据库事务中清理课程关联记录，并将文件目录先移入回收区，事务失败时恢复。
- DATA-02 / DATA-03：解析改为材料版本与活动版本模型；旧 chunk 保留，知识点按课程与规范化标题增量更新，未出现的点归档。
- QUIZ-01 / QUIZ-02 / QUIZ-03：选项改为 `{label,text,value}`；前端发送选项字母，多选以数组提交并做集合比较；题目保存经过课程与活动版本校验的来源证据 ID。
- PLAN-01：移除新生成的 `practice`，并将历史 `practice` / `exercise` / `test` 归一化为 `quiz`。
- GRAPH-02：没有可访问原始资料证据时返回 `insufficient_evidence`，不产生正式语义结论。
- LLM-01 / AUDIT-01：用户模型失败后尝试系统真实模型，再降级 Mock；调用元数据携带请求与实际 provider/model、fallback 链及 degraded 状态。

## 数据迁移

- 入口：[scripts/migrate.py](../scripts/migrate.py)
- `--dry-run` 已验证。实际迁移会先备份 SQLite 数据库，再添加兼容列和规范化历史任务类型；本次未写入现有学习数据库。

## 测试结果

- `python -m pytest -q backend/app/tests/test_courses.py backend/app/tests/test_materials.py backend/app/tests/test_parse.py backend/app/tests/test_quizzes.py backend/app/tests/test_knowledge_points.py backend/app/tests/test_llm.py backend/app/tests/test_concept_compare_agent.py`：84 passed。
- `npm run type-check`：通过。
- `npm run build`：通过（存在第三方 pure annotation 与大 chunk 警告）。
- `git diff --check`：通过。

## 未完成项与风险

- 第二轮计划中的简答 rubric、薄弱点恢复、RAG 多轮引用验证、可执行计划目标、排程溢出、概念缓存、文档解析质量与检索统计尚未实施。
- 全量 `backend/app/tests` 在本环境 60 秒命令限制内超时，未可声明全量通过。
- SQLite 对 `materials` 与 `material_versions` 的双向外键在测试 teardown 时提示排序警告；功能测试通过，但未来建议迁移到显式 Alembic 迁移并用 `use_alter` 或单向约束消除该告警。

## 回滚

- 代码：回滚本轮独立提交。
- 数据：使用 `scripts/migrate.py` 生成的 `.backup-<timestamp>` SQLite 备份。
