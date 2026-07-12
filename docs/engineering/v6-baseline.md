# V6 Baseline — 真实功能闭环与学习质量完成计划

## 起始基线

- **起始 commit:** `6ac465d` (Merge PR #5 — function-quality-closure-v5-final)
- **分支:** `main`
- **日期:** 2026-07-12
- **Python:** 3.12+ (backend/.venv)
- **Node:** 18+ (frontend)
- **迁移版本:** 013 (v5_task_completion_fields)
- **当前测试数量:** ~80+ backend tests, 7 frontend unit tests, 6 E2E specs

## P0 阻断项

1. learn 任务页面没有提交 `target_loaded`，正常 UI 路径无法完成任务
2. 现有 E2E 存在"测试名称很强、实际断言很弱"的情况
3. Chunk 仍可能按固定字符窗口截断，未形成真正语义分块
4. 测验生成没有严格服从 `question_count`
5. 知识点标题过滤仍可能误伤 `TCP/IP`、`CSMA/CD`
6. ParseJob 仍由 FastAPI BackgroundTasks 执行，不具备真正进程重启恢复
7. Task、Todo、Goal 的状态变化仍分散在多个入口中

## P1 高优先级问题

1. 阅读页目录只有页码，原文、清洗文本和 Chunk 可能重复展示
2. 清洗决策虽然入库，但用户无法查看删除原因
3. 多课程计划只有创建路径，缺少读取、修改、重排和删除闭环
4. 图片损坏和重新提取缺少完整 UI
5. FTS 索引在查询时整体重建，成本和并发语义不合理
6. 知识点"重新生成"的前端文案与后端归档语义不一致
7. 关键业务场景未进入最终验收清单

## V6 验收报告要求

每次验收运行必须记录:
- commit SHA
- 每条命令
- exit code
- passed、failed、skipped
- 场景 ID
- 断言摘要
- fixture 哈希
- 数据库文件是否独立创建

## Fixtures

| Fixture | SHA-256 (前16位) | 用途 |
|---------|------------------|------|
| `networking-two-column.pdf` | `aa4212429ae6e980` | 双栏PDF解析、TCP/IP术语保留 |
| `operating-system-slides.pptx` | `9fce6b581ffc621c` | PPTX多级列表、表格、形状 |
| `image-heavy-course.pdf` | `ba55a2ec5786d4e2` | 图片提取完整性测试 |
| `corrupted-sample.pdf` | `b4f935ec81e55df1` | 解析失败处理 |
