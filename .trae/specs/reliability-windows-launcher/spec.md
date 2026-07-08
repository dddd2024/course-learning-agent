# 可靠性修复与 Windows 快捷启动 实施计划

> 来源：`课程学习助手_可靠性修复与Windows快捷启动计划.docx`
> 仓库：dddd2024/course-learning-agent
> 分支：main
> 基线提交：2c60dfa

## 背景

上一轮提交（2c60dfa）已完成 ErrorLog 表、/logs 接口、日志中心页面、解析重试、解析超时恢复和时间统一。审计后仍存在以下缺口：
- 上传失败无日志、无脏数据清理
- 解析请求同步阻塞前端
- Agent 错误只写旧 AgentErrorLog，不进日志中心
- 资料页 stale-ready 行无"查看原因"入口
- 旧 naive 时间数据未修正
- 无 Windows 桌面快捷启动

## 目标

1. **上传失败清理 + 日志**：上传类型/大小/磁盘写入失败时写 ErrorLog(category=upload)，回滚脏 Material 行。
2. **解析后台化**：parse endpoint 改用 FastAPI BackgroundTasks，立即返回 processing；前端轮询获取最终状态。
3. **Agent 错误接入日志中心**：chat_service 的 retrieve/generate 失败时同时写 ErrorLog(category=agent)。
4. **资料页交互修正**：stale-ready 行也显示"查看原因"。
5. **旧时间数据修正脚本**：scripts/fix_legacy_material_time.py（dry-run 默认，--apply 写入）。
6. **Windows 一键启动**：start_windows.ps1 + create_desktop_shortcut.ps1，Edge/Chrome --app 模式。

## 非目标

- 不引入 Electron/Tauri/Celery/Redis。
- 不记录成功操作。
- 不重写 RAG/问答/知识图谱主流程。
- 不处理生产部署，只服务本地开发和课程展示。

## 设计决策

- **上传清理**：try/except 包裹磁盘写入，失败时 `db.delete(material)` + `db.commit()` 回滚，再写 ErrorLog。
- **解析后台化**：`parse_material` 改用 `BackgroundTasks`；设置 processing 状态后立即返回；后台任务调用 `parse_with_retry`。processing 中再请求返回当前状态。
- **Agent 错误桥接**：chat_service `_log_error` 内额外调用 `log_error(category="agent")`，保留旧 AgentErrorLog 不破坏审计页。
- **Windows 启动**：PowerShell 启动后端+前端，Edge `--app` 模式打开；.lnk 快捷方式指向 ps1。

## 任务分解

### Task A：上传失败清理与上传日志（TDD）

文件：
- 修改：`backend/app/api/v1/endpoints/materials.py`（upload_material 加 try/except + log_error）
- 新增：`backend/app/tests/test_material_upload_error_log.py`

### Task B：资料解析后台化与超时恢复（TDD）

文件：
- 修改：`backend/app/api/v1/endpoints/parse.py`（parse_material 改用 BackgroundTasks）
- 修改：`backend/app/services/material_parser.py`（parse_with_retry 适配后台调用）
- 修改：`frontend/src/views/MaterialsView.vue`（handleParse 不等待完成，提示已提交）
- 新增：`backend/app/tests/test_parse_background_tasks.py`

### Task C：日志中心补全 Agent 错误接入（TDD）

文件：
- 修改：`backend/app/services/chat_service.py`（_log_error 额外写 ErrorLog）
- 新增：`backend/app/tests/test_agent_error_log_bridge.py`

### Task D：资料页失败状态交互修正

文件：
- 修改：`frontend/src/views/MaterialsView.vue`（stale-ready 也显示"查看原因"）

### Task E：旧时间数据处理脚本

文件：
- 新增：`scripts/fix_legacy_material_time.py`（dry-run 默认，--apply 写入）

### Task F：Windows 一键启动与桌面快捷方式

文件：
- 新增：`scripts/start_windows.ps1`
- 新增：`scripts/create_desktop_shortcut.ps1`

## 验收

```powershell
cd backend; python -m pytest app/tests/ -q
cd ../frontend; npm run build
cd ..; pwsh .\scripts\verify_phase2_engineering.ps1
pwsh .\scripts\create_desktop_shortcut.ps1
```

## 提交建议

- 提交 1：`fix(reliability): harden upload cleanup, async parse, and log coverage`（Tasks A-E）
- 提交 2：`feat(windows-launcher): add app-like desktop shortcut startup scripts`（Task F）
