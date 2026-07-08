# 阶段收尾小修复 Implementation Plan

> **Goal:** 三个小 hardening 修复——UserResponse 默认不返回 raw email、start_windows.ps1 依赖安装去重、health check 增加项目标识——使系统在演示和报告表述上更稳。

**来源:** `课程学习助手_阶段收尾小修复计划.docx`

**Architecture:** 不扩展新功能，不改动课程核心业务逻辑。仅 (A) 收紧用户信息接口响应、(B) 优化启动器依赖安装策略、(C) 强化 health check 与启动器端口复用判断。

**Tech Stack:** FastAPI + Pydantic v2 / pytest / PowerShell / Vue 3 + TS

---

## Task A: UserResponse 默认不返回 raw email

**Files:**
- Modify: `backend/app/schemas/user.py`
- Modify: `backend/app/api/v1/endpoints/auth.py`
- Modify: `backend/app/tests/test_auth_security.py`
- Modify: `frontend/src/api/auth.ts`

- [ ] **A1 RED**: 新增测试 `test_me_does_not_return_raw_email` / `test_register_does_not_return_raw_email`，断言响应体不含 `email` 键，只含 `email_masked`；并覆盖空邮箱与异常邮箱格式。
- [ ] **A2 RED 验证**: 运行 pytest 确认新测试失败（当前仍返回 email）。
- [ ] **A3 GREEN**: `UserResponse` 移除 `email` 字段，仅保留 `email_masked`；`model_validator` 改为基于传入的 `email_masked`（endpoints 显式传 `email_masked=mask_email(user.email)`）。更新 `register` / `me`。
- [ ] **A4 GREEN 验证**: 全量 auth 测试通过。
- [ ] **A5 前端**: `UserInfo` 删除 `email`，新增 `email_masked: string | null`。

## Task B: start_windows.ps1 依赖安装标记

**Files:**
- Modify: `scripts/start_windows.ps1`
- Modify: `docs/engineering/dev_startup.md`

- [ ] **B1**: 新增标记文件 `backend/.venv/.requirements_installed`；比较 `requirements.txt` LastWriteTime 与标记文件时间，仅当标记缺失或 requirements 更新时执行 `pip install`。安装成功后写标记，失败不写。
- [ ] **B2**: 输出 `Backend dependencies already installed, skipping pip install.`
- [ ] **B3**: 更新 `docs/engineering/dev_startup.md` 说明该行为。

## Task C: health check 增加项目标识

**Files:**
- Modify: `backend/app/api/v1/endpoints/health.py`
- Modify: `backend/app/tests/test_health.py`
- Modify: `scripts/start_windows.ps1`

- [ ] **C1 RED**: 更新 `test_health_returns_ok` 并新增 `test_health_returns_app_identifier`，断言响应含 `status=ok`、`app=course-learning-agent`、`version` 字段。
- [ ] **C2 RED 验证**: 测试失败。
- [ ] **C3 GREEN**: `health_check` 返回 `{status, app, version}`。
- [ ] **C4 GREEN 验证**: 测试通过。
- [ ] **C5**: `start_windows.ps1` 后端 8000 端口复用时请求 `/api/v1/health`，校验响应包含 `course-learning-agent`，否则提示端口被其他后端占用并退出。

## Task D: 全量验收 + 提交推送

- [ ] **D1**: 后端 pytest 全量通过；前端 `npm run build` 通过；`verify_phase2_engineering.ps1` 通过。
- [ ] **D2**: conventional commit + push to `origin/main`。
