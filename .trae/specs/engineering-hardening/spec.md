# 工程补强计划 Implementation Plan

> **For agentic workers:** TDD-driven execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把课程学习助手补强为"能稳定跑、能复现验收、能定位问题、能支撑答辩展示"的工程化作品。包含审计遗留收尾、CI 验收闭环、API 契约测试、E2E 测试与演示种子数据。Agent 审计展示闭环已存在，本轮仅修复状态词表不一致。

**Architecture:** Phase 0 修三个边界 bug；Phase 1 加 Linux 验收脚本 + CI artifact 上传；Phase 2 锁定 API 响应契约；Phase 3 修前后端状态词表不一致 + E2E 测试；Phase 4 演示种子数据 + README。不重构主流程、不引入向量数据库、不做报告/PPT。

**Tech Stack:** FastAPI + Pydantic v2 + SQLAlchemy（后端）；Vue 3 + TypeScript + Element Plus（前端）；pytest + vue-tsc + PowerShell/bash 验收脚本；GitHub Actions CI。

---

## 文件结构

| 文件 | 责任 | 修改类型 |
|------|------|----------|
| `backend/app/schemas/multi_plan.py` | `MultiCourseInput` 归一化逻辑改为 `model_validator` | Modify |
| `backend/app/services/multi_scheduler.py` | `user_priority=0.0` 不被 `or 0.5` 覆盖 | Modify |
| `backend/app/core/config.py` | `ENVIRONMENT` 大小写不敏感 | Modify |
| `backend/app/tests/test_multi_plans.py` | 新增 priority=1→0.2、user_priority=0.0 测试 | Modify |
| `backend/app/tests/test_health.py` | 新增 `ENVIRONMENT="Production"` 测试 | Modify |
| `scripts/verify_phase2_engineering.sh` | Linux 版验收脚本 | Create |
| `.github/workflows/ci.yml` | 上传 artifact | Modify |
| `README.md` | 验收复现命令区块 | Modify |
| `backend/app/tests/test_api_contracts.py` | API 契约测试 | Create |
| `frontend/src/views/AgentRunsView.vue` | 状态词表对齐后端 (`running`/`success`/`failed`) | Modify |
| `backend/app/tests/test_e2e_learning_flow.py` | E2E 流程测试 | Create |
| `scripts/seed_demo_data.py` | 演示种子数据 | Create |

---

## Task 1: T0-1 — priority=1 应归一化为 0.2（而非 1.0）

**问题**：当前 `c.user_priority > 1` 判断把 `priority=1` 当成已归一化的 0-1 值，直接保留为 1.0，但 1-5 旧字段里的 1 应该是最低优先级（归一化为 0.2）。

**Files:**
- Modify: `backend/app/schemas/multi_plan.py`
- Modify: `backend/app/api/v1/endpoints/plans.py`
- Test: `backend/app/tests/test_multi_plans.py`

- [ ] **Step 1: 写失败测试 — priority=1 归一化为 0.2**

在 `test_multi_plans.py` 末尾新增：

```python
def test_priority_1_normalizes_to_02(client, monkeypatch) -> None:
    """T0-1: 旧字段 priority=1 应归一化为 0.2，不是 1.0。"""
    from app.api.v1.endpoints import plans as plans_module

    captured: dict = {}

    def fake_schedule(db, user_id, courses, daily_minutes, user_config=None):
        captured["courses"] = courses
        return {"schedule": [], "overflow_warnings": []}

    monkeypatch.setattr(plans_module, "schedule_multi_courses", fake_schedule)

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="边界课程")
    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [
                {"course_id": course_id, "deadline": "2099-01-01", "priority": 1}
            ],
            "daily_minutes": 120,
            "constraints": {},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    # priority=1（1-5 旧字段）应归一化为 0.2
    assert captured["courses"][0]["user_priority"] == 0.2
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest app/tests/test_multi_plans.py::test_priority_1_normalizes_to_02 -v`
Expected: FAIL — `assert 1.0 == 0.2`（当前 `1 > 1` 为假，保留 1.0）

- [ ] **Step 3: 实现 — 用 `model_validator` 区分新旧字段**

修改 `backend/app/schemas/multi_plan.py`，加 `model_validator(mode="before")` 区分 `priority`（旧 1-5）与 `user_priority`（新 0-1）：

```python
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


def _normalize_priority_input(data: dict) -> dict:
    """T0-1: 区分 priority（旧 1-5）与 user_priority（新 0-1）。

    - 旧字段 priority（1-5）除以 5 归一化为 0-1
    - 新字段 user_priority（0-1）保持不变
    - 两者都提供时优先 user_priority
    """
    if not isinstance(data, dict):
        return data
    data = dict(data)
    if "user_priority" in data and data["user_priority"] is not None:
        return data
    if "priority" in data and data["priority"] is not None:
        try:
            v = float(data["priority"])
            data["user_priority"] = v / 5.0
        except (TypeError, ValueError):
            pass
    return data


class MultiCourseInput(BaseModel):
    """A single course entry in a POST /plans/multi request.

    ``user_priority`` 兼容两种输入：
    - 新格式：0-1 的浮点数（如 0.8），直接生效
    - 旧格式：1-5 的整数（如 4），由 ``_normalize_priority_input`` 归一化为 0-1

    旧前端发送的 ``priority`` 字段通过 ``AliasChoices`` 被接受，
    ``model_validator(mode="before")`` 负责把 1-5 归一化为 0-1。
    """

    course_id: int
    deadline: date
    user_priority: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_priority(cls, data):
        return _normalize_priority_input(data)
```

- [ ] **Step 4: 删除 `plans.py` 中的旧归一化逻辑**

修改 `backend/app/api/v1/endpoints/plans.py` 的 `courses_input` 构建处，去掉 `> 1` 判断（归一化已在 schema 层完成）：

```python
    courses_input = [
        {
            "course_id": c.course_id,
            "deadline": c.deadline,
            "user_priority": c.user_priority,
        }
        for c in payload.courses
    ]
```

- [ ] **Step 5: 运行测试验证通过**

Run: `cd backend && python -m pytest app/tests/test_multi_plans.py -v`
Expected: PASS

---

## Task 2: T0-2 — user_priority=0.0 不应被 or 0.5 覆盖

**问题**：`float(c.get("user_priority") or 0.5)` 中 `0.0 or 0.5` 结果为 `0.5`，因为 `0.0` 是 falsy。

**Files:**
- Modify: `backend/app/services/multi_scheduler.py`
- Test: `backend/app/tests/test_multi_plans.py`

- [ ] **Step 1: 写失败测试 — user_priority=0.0 保留为 0.0**

在 `test_multi_plans.py` 新增：

```python
def test_user_priority_zero_not_overridden(client, monkeypatch) -> None:
    """T0-2: 显式 user_priority=0.0 不应被默认值 0.5 覆盖。"""
    from app.api.v1.endpoints import plans as plans_module

    captured: dict = {}

    def fake_schedule(db, user_id, courses, daily_minutes, user_config=None):
        captured["courses"] = courses
        return {"schedule": [], "overflow_warnings": []}

    monkeypatch.setattr(plans_module, "schedule_multi_courses", fake_schedule)

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="零优先级课程")
    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [
                {
                    "course_id": course_id,
                    "deadline": "2099-01-01",
                    "user_priority": 0.0,
                }
            ],
            "daily_minutes": 120,
            "constraints": {},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured["courses"][0]["user_priority"] == 0.0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest app/tests/test_multi_plans.py::test_user_priority_zero_not_overridden -v`
Expected: FAIL — `assert 0.5 == 0.0`（API 层透传 0.0，但 scheduler 内部 `or 0.5` 覆盖；注意此测试 monkeypatch 了 scheduler，所以 0.0 会透传到 captured——需要确认测试是否真能抓到 scheduler 内部 bug）

注意：此测试 monkeypatch 了 `schedule_multi_courses`，所以 0.0 会透传到 captured，测试会通过。要抓 scheduler 内部 bug，需要直接测 scheduler。改为：

```python
def test_user_priority_zero_not_overridden_in_scheduler(monkeypatch) -> None:
    """T0-2: scheduler 内部 user_priority=0.0 不应被 or 0.5 覆盖。"""
    from datetime import date

    from app.services import multi_scheduler

    captured_priorities: list = []

    def fake_planner_generate(
        db, user_id, goal, courses, deadline, daily_minutes, user_config=None
    ):
        return {"tasks": []}

    monkeypatch.setattr(multi_scheduler, "planner_generate", fake_planner_generate)

    class _DummyDb:
        def query(self, *a, **k):
            class _Q:
                def filter(self, *a, **k):
                    return self

                def all(self):
                    return []

                def scalar(self):
                    return 0

            return _Q()

    # 捕获传入 compute_priority_score 的 user_priority
    original_compute = multi_scheduler.compute_priority_score

    def spy_compute(deadline_urgency, workload_weight, weak_point_weight, user_priority):
        captured_priorities.append(user_priority)
        return original_compute(
            deadline_urgency, workload_weight, weak_point_weight, user_priority
        )

    monkeypatch.setattr(multi_scheduler, "compute_priority_score", spy_compute)

    multi_scheduler.schedule_multi_courses(
        db=_DummyDb(),
        user_id=1,
        courses=[
            {"course_id": 1, "deadline": date(2099, 1, 1), "user_priority": 0.0}
        ],
        daily_minutes=120,
    )

    assert 0.0 in captured_priorities, "user_priority=0.0 应被保留，不应被 0.5 覆盖"
```

- [ ] **Step 3: 实现 — 用 `is None` 判断代替 `or`**

修改 `backend/app/services/multi_scheduler.py` 第 140 行：

```python
        raw_priority = c.get("user_priority")
        user_priority = float(raw_priority) if raw_priority is not None else 0.5
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest app/tests/test_multi_plans.py::test_user_priority_zero_not_overridden_in_scheduler -v`
Expected: PASS

---

## Task 3: T0-3 — ENVIRONMENT 大小写不敏感

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/app/tests/test_health.py`

- [ ] **Step 1: 写失败测试 — `ENVIRONMENT="Production"` 触发校验**

在 `test_health.py` 新增：

```python
def test_prod_rejects_default_jwt_secret_case_insensitive() -> None:
    """T0-3: ENVIRONMENT="Production" 也应触发生产校验。"""
    from app.core.config import Settings

    s = Settings(
        ENVIRONMENT="Production",
        JWT_SECRET_KEY="change_me",
        LLM_CONFIG_SECRET_KEY="a-valid-fernet-key",
    )
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        s.validate_prod_secrets()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest app/tests/test_health.py::test_prod_rejects_default_jwt_secret_case_insensitive -v`
Expected: FAIL — 不抛异常（"Production" != "production"）

- [ ] **Step 3: 实现 — `validate_prod_secrets` 用 `.lower()`**

修改 `backend/app/core/config.py` 的 `validate_prod_secrets`：

```python
    def validate_prod_secrets(self) -> None:
        if self.ENVIRONMENT.lower() != "production":
            return
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest app/tests/test_health.py -v`
Expected: PASS

- [ ] **Step 5: 提交 Phase 0**

```bash
git add backend/app/schemas/multi_plan.py backend/app/services/multi_scheduler.py backend/app/core/config.py backend/app/api/v1/endpoints/plans.py backend/app/tests/test_multi_plans.py backend/app/tests/test_health.py
git commit -m "fix(audit): close priority and environment edge cases"
```

---

## Task 4: Phase 1 — Linux 验收脚本 + CI artifact

**Files:**
- Create: `scripts/verify_phase2_engineering.sh`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`

- [ ] **Step 1: 创建 `scripts/verify_phase2_engineering.sh`（移植 PowerShell 版）**

```bash
#!/usr/bin/env bash
# Phase 2 Engineering Bugfix Acceptance Script (Linux)
# Usage: bash ./scripts/verify_phase2_engineering.sh
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

failed=0
ok()   { echo "[OK] $1"; }
bad()  { echo "[FAIL] $1"; failed=1; }
step() { echo ""; echo "=== $1 ==="; }

# 1. Backend tests
step "Backend pytest"
cd "$root/backend"
if python -m pytest app/tests/ -q; then ok "backend tests passed"; else bad "backend tests failed"; fi
cd "$root"

# 2. Frontend build
step "Frontend build"
cd "$root/frontend"
if npm run build >/dev/null 2>&1; then ok "frontend build passed"; else bad "frontend build failed"; fi
cd "$root"

# 3. Subjective metric UI residue check
step "Subjective metric UI residue check"
if grep -rE '可靠性|相关度|confidencePercent|命中率' "$root/frontend/src" --include='*.vue' --include='*.ts'; then
  bad "subjective metric UI residue found"
else
  ok "no subjective metric UI residue"
fi

# 4. algorithmic-art removed
step "algorithmic-art removal check"
if [ -d "$root/algorithmic-art" ]; then bad "algorithmic-art/ still exists"; else ok "algorithmic-art/ removed"; fi

# 5. CI workflow_dispatch trigger present
step "CI workflow_dispatch trigger check"
if grep -q 'workflow_dispatch' "$root/.github/workflows/ci.yml"; then ok "CI workflow_dispatch present"; else bad "CI workflow_dispatch missing"; fi

# 6. Production hardening check
step "Production hardening check"
main_py="$root/backend/app/main.py"
config_py="$root/backend/app/core/config.py"
if grep -q 'allow_origins=\["\*"\]' "$main_py"; then bad 'main.py hardcodes allow_origins=["*"]'; else ok "main.py uses config-driven CORS"; fi
if grep -q 'ENVIRONMENT' "$config_py" && grep -q 'CORS_ORIGINS' "$config_py" && grep -q 'def validate_prod_secrets' "$config_py"; then
  ok "config.py defines ENVIRONMENT/CORS_ORIGINS/validate_prod_secrets"
else
  bad "config.py missing hardening fields"
fi

# 7. Audit-submit-rectification checks
step "Audit-submit-rectification checks"
multi_plan="$root/backend/app/schemas/multi_plan.py"
plans_py="$root/backend/app/api/v1/endpoints/plans.py"
scheduler_py="$root/backend/app/services/multi_scheduler.py"
plan_ts="$root/frontend/src/api/plan.ts"

if grep -q 'AliasChoices' "$multi_plan" && grep -q 'priority' "$multi_plan"; then ok "MultiCourseInput accepts both priority and user_priority"; else bad "MultiCourseInput missing AliasChoices"; fi
if grep -q 'user_config' "$scheduler_py"; then ok "schedule_multi_courses accepts user_config"; else bad "schedule_multi_courses missing user_config"; fi
if grep -q 'get_active_config' "$plans_py" && grep -q 'user_config=user_config' "$plans_py"; then ok "create_multi_plan passes user_config"; else bad "create_multi_plan missing user_config"; fi
if ! grep -q 'goal_ids' "$plan_ts"; then ok "frontend MultiPlanResult has no goal_ids"; else bad "frontend still has goal_ids"; fi
if grep -q '"\*" in origins' "$config_py"; then ok "config.py rejects wildcard CORS"; else bad "config.py missing wildcard rejection"; fi

echo ""
if [ "$failed" -eq 0 ]; then echo "ACCEPTANCE PASSED"; exit 0; else echo "ACCEPTANCE FAILED"; exit 1; fi
```

- [ ] **Step 2: 修改 `.github/workflows/ci.yml` 加 artifact 上传**

在 backend-test job 末尾加 artifact 上传：

```yaml
      - name: Run pytest
        run: |
          cd backend
          python -m pytest app/tests/ -q 2>&1 | tee ../backend-test-result.txt

      - name: Upload backend test result
        uses: actions/upload-artifact@v4
        with:
          name: backend-test-result
          path: backend-test-result.txt
```

在 frontend-build job 的 Build 步骤加 tee + 上传：

```yaml
      - name: Build
        run: |
          cd frontend
          npm run build 2>&1 | tee ../frontend-build-result.txt

      - name: Upload frontend build result
        uses: actions/upload-artifact@v4
        with:
          name: frontend-build-result
          path: frontend-build-result.txt
```

新增 acceptance job：

```yaml
  acceptance:
    name: Acceptance Script
    runs-on: ubuntu-latest
    needs: [backend-test, frontend-build]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - name: Install backend deps
        run: python -m pip install -r backend/requirements.txt
      - name: Install frontend deps
        run: cd frontend && npm ci
      - name: Run acceptance
        run: |
          bash ./scripts/verify_phase2_engineering.sh 2>&1 | tee acceptance-result.txt
      - name: Upload acceptance result
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: acceptance-result
          path: acceptance-result.txt
```

- [ ] **Step 3: README 加"如何复现验收"区块**

在 README.md 合适位置加：

```markdown
## 如何复现验收

### Windows (PowerShell)
```powershell
cd backend; python -m pytest app/tests/ -q
cd ..\frontend; npm run build
cd ..; pwsh ./scripts/verify_phase2_engineering.ps1
```

### Linux / macOS (bash)
```bash
cd backend && python -m pytest app/tests/ -q
cd ../frontend && npm run build
cd .. && bash ./scripts/verify_phase2_engineering.sh
```

### CI 自动验收
推送到 `main` 后 GitHub Actions 会自动运行 backend pytest、frontend build、acceptance script，并上传 `backend-test-result.txt`、`frontend-build-result.txt`、`acceptance-result.txt` 三类 artifact，可在 Actions 页面下载。
```

- [ ] **Step 4: 提交 Phase 1**

```bash
git add scripts/verify_phase2_engineering.sh .github/workflows/ci.yml README.md
git commit -m "ci: add linux acceptance script and artifacts"
```

---

## Task 5: Phase 2 — API 契约测试

**Files:**
- Create: `backend/app/tests/test_api_contracts.py`

- [ ] **Step 1: 创建契约测试文件**

```python
"""API contract tests — lock the response shape of core endpoints.

These tests do NOT assert business logic correctness; they only assert
that the response structure (field names, types, nesting) stays stable
so frontend/backend refactors cannot silently break the contract.
"""
from app.tests.conftest import auth_headers, create_course


def test_multi_plan_response_contract(client) -> None:
    """POST /plans/multi 返回 {schedule: [...], overflow_warnings: [...]}。"""
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="契约课程")
    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [{"course_id": course_id, "deadline": "2099-01-01"}],
            "daily_minutes": 120,
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {"schedule", "overflow_warnings"}
    assert isinstance(body["schedule"], list)
    assert isinstance(body["overflow_warnings"], list)
    for item in body["schedule"]:
        assert set(item.keys()) >= {
            "scheduled_date", "course_name", "title", "estimate_minutes",
            "start_time", "end_time",
        }


def test_chat_response_contract(client) -> None:
    """POST /chat 返回 {message_id, answer, citations, retrieved_chunks, fallback_used, fallback_reason}。"""
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="聊天契约课程")
    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "question": "测试问题",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {
        "message_id", "answer", "citations", "retrieved_chunks",
        "fallback_used", "fallback_reason",
    }


def test_error_response_contract(client) -> None:
    """404 错误返回稳定结构 {detail: {message: ...}} 或 {detail: ...}。"""
    headers = auth_headers(client, username="alice")
    resp = client.get("/api/v1/courses/999999/materials", headers=headers)
    assert resp.status_code == 404
    body = resp.json()
    # detail 可以是 string 或 {message: ...}
    assert "detail" in body
```

- [ ] **Step 2: 运行测试**

Run: `cd backend && python -m pytest app/tests/test_api_contracts.py -v`
Expected: PASS（如有字段不匹配，调整测试断言以匹配实际契约，**不改业务代码**）

- [ ] **Step 3: 提交 Phase 2**

```bash
git add backend/app/tests/test_api_contracts.py
git commit -m "test(contract): lock api response contracts"
```

---

## Task 6: Phase 3 — Agent 审计状态词表对齐

**问题**：后端写 `running`/`success`/`failed`，前端 `AgentRunsView.vue` 期望 `started`/`succeeded`/`failed`，导致状态标签 fallback 到原始值。

**Files:**
- Modify: `frontend/src/views/AgentRunsView.vue`

- [ ] **Step 1: 读取 `AgentRunsView.vue` 状态映射部分**

定位 `statusOptions`、`statusLabel`、`statusTagType`、`stepStatus` 四处。

- [ ] **Step 2: 把前端词表改为 `running`/`success`/`failed`**

修改 `statusOptions`：
```typescript
const statusOptions = [
  { value: 'running', label: '运行中' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
]
```

修改 `statusLabel`：
```typescript
function statusLabel(s: string): string {
  return { running: '运行中', success: '成功', failed: '失败' }[s] || s
}
```

修改 `statusTagType`：
```typescript
function statusTagType(s: string): string {
  return { running: 'info', success: 'success', failed: 'danger' }[s] || 'info'
}
```

修改 `stepStatus`：
```typescript
function stepStatus(s: string): string {
  return { success: 'success', failed: 'error', running: 'process' }[s] || 'wait'
}
```

- [ ] **Step 3: 运行前端构建**

Run: `cd frontend && npm run build`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/AgentRunsView.vue
git commit -m "fix(audit): align agent run status vocabulary with backend"
```

---

## Task 7: Phase 4 — E2E 学习流程测试

**Files:**
- Create: `backend/app/tests/test_e2e_learning_flow.py`

- [ ] **Step 1: 创建 E2E 测试**

```python
"""End-to-end learning flow test.

Covers: register/login → create course → upload material → parse →
create conversation → ask question → generate knowledge points →
create single-course plan → create multi-course plan.

This is an API-level E2E test (no Playwright/browser). It verifies
the full learning flow works end-to-end with the mock LLM provider.
"""
from app.tests.conftest import auth_headers, create_course


def test_full_learning_flow(client) -> None:
    """完整学习助手流程跑通。"""
    headers = auth_headers(client, username="demo_user")

    # 1. 创建课程
    course_id = create_course(client, headers, name="操作系统")

    # 2. 上传资料（用最小 txt 内容）
    upload_resp = client.post(
        "/api/v1/materials/upload",
        headers=headers,
        data={"course_id": str(course_id)},
        files={"file": ("note.txt", b"进程是程序在数据集合上运行的过程\n线程是进程内的执行单元\n", "text/plain")},
    )
    assert upload_resp.status_code in (200, 201), upload_resp.text
    material_id = upload_resp.json()["id"]

    # 3. 解析资料
    parse_resp = client.post(f"/api/v1/materials/{material_id}/parse", headers=headers)
    assert parse_resp.status_code == 200, parse_resp.text

    # 4. 创建对话并提问
    chat_resp = client.post(
        "/api/v1/chat",
        json={"course_id": course_id, "question": "什么是进程？"},
        headers=headers,
    )
    assert chat_resp.status_code == 200, chat_resp.text
    chat_body = chat_resp.json()
    assert "answer" in chat_body
    assert isinstance(chat_body["answer"], str)

    # 5. 生成单课程计划
    plan_resp = client.post(
        "/api/v1/plans",
        json={
            "goal": "掌握操作系统",
            "courses": ["操作系统"],
            "deadline": "2099-01-01",
            "daily_minutes": 120,
        },
        headers=headers,
    )
    assert plan_resp.status_code == 200, plan_resp.text

    # 6. 生成多课程计划
    course_id_2 = create_course(client, headers, name="数据库")
    multi_resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [
                {"course_id": course_id, "deadline": "2099-01-01"},
                {"course_id": course_id_2, "deadline": "2099-01-01"},
            ],
            "daily_minutes": 120,
        },
        headers=headers,
    )
    assert multi_resp.status_code == 200, multi_resp.text
    assert "schedule" in multi_resp.json()
```

- [ ] **Step 2: 运行 E2E 测试**

Run: `cd backend && python -m pytest app/tests/test_e2e_learning_flow.py -v`
Expected: PASS（如有端点路径不符，根据实际调整，**不改业务代码**）

---

## Task 8: Phase 4 — 演示种子数据脚本

**Files:**
- Create: `scripts/seed_demo_data.py`
- Modify: `README.md`

- [ ] **Step 1: 创建 `scripts/seed_demo_data.py`**

```python
"""Seed demo data for course-learning-agent.

Usage: python scripts/seed_demo_data.py

Creates a demo user, two courses (操作系统 / 数据库), sample materials,
parsed chunks, a conversation, and study plans so the platform is
immediately demoable after a fresh database init.
"""
import sys
from pathlib import Path

# 让脚本能 import backend 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.course import Course  # noqa: E402
from app.models.material import Material  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.chunk import Chunk  # noqa: E402


def seed() -> None:
    db = SessionLocal()
    try:
        # 1. Demo user
        demo = db.query(User).filter(User.username == "demo").first()
        if demo is None:
            demo = User(username="demo", password=hash_password("demo123"))
            db.add(demo)
            db.flush()
            print(f"[seed] created user demo (id={demo.id})")
        else:
            print(f"[seed] user demo exists (id={demo.id})")

        # 2. Courses
        courses_data = [
            ("操作系统", "2025秋季", "张老师"),
            ("数据库", "2025秋季", "李老师"),
        ]
        course_ids: dict[str, int] = {}
        for name, semester, teacher in courses_data:
            c = db.query(Course).filter(
                Course.user_id == demo.id, Course.name == name
            ).first()
            if c is None:
                c = Course(
                    user_id=demo.id, name=name, semester=semester, teacher=teacher
                )
                db.add(c)
                db.flush()
                print(f"[seed] created course {name} (id={c.id})")
            else:
                print(f"[seed] course {name} exists (id={c.id})")
            course_ids[name] = c.id

        # 3. Sample material + chunks for 操作系统
        os_mat = db.query(Material).filter(
            Material.course_id == course_ids["操作系统"]
        ).first()
        if os_mat is None:
            os_mat = Material(
                course_id=course_ids["操作系统"],
                filename="操作系统笔记.txt",
                file_type="txt",
                status="ready",
            )
            db.add(os_mat)
            db.flush()
            print(f"[seed] created material {os_mat.filename} (id={os_mat.id})")
            for i, (title, text) in enumerate([
                ("进程", "进程是程序在数据集合上运行的过程，是系统资源分配的基本单位。"),
                ("线程", "线程是进程内的执行单元，是 CPU 调度的基本单位。"),
            ]):
                db.add(Chunk(
                    material_id=os_mat.id,
                    course_id=course_ids["操作系统"],
                    title=title,
                    text=text,
                    chunk_index=i,
                ))
            print("[seed] created 2 chunks for 操作系统")

        db.commit()
        print("[seed] done. Login: demo / demo123")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
```

- [ ] **Step 2: README 加演示启动步骤**

在 README 的"如何复现验收"之后加：

```markdown
## 演示数据

```bash
cd backend
python -m app.core.database  # 初始化表（如已有可跳过）
python ../scripts/seed_demo_data.py
```

启动后端后用 `demo / demo123` 登录即可看到预置的操作系统、数据库课程和示例资料。
```

- [ ] **Step 3: 提交 Phase 3 + 4**

```bash
git add backend/app/tests/test_e2e_learning_flow.py scripts/seed_demo_data.py README.md
git commit -m "test(e2e): add learning flow and demo seed data"
```

---

## Task 9: 全量验收 + 推送 + 触发 CI

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && python -m pytest app/tests/ -q`
Expected: 全部通过

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 无错误

- [ ] **Step 3: Windows 验收脚本**

Run: `pwsh ./scripts/verify_phase2_engineering.ps1`
Expected: ACCEPTANCE PASSED

- [ ] **Step 4: Linux 验收脚本（如环境支持）**

Run: `bash ./scripts/verify_phase2_engineering.sh`
Expected: ACCEPTANCE PASSED

- [ ] **Step 5: 推送**

```bash
git push origin main
```

- [ ] **Step 6: 触发 CI 并验证 artifact**

```bash
gh workflow run CI --ref main
```
确认 backend-test、frontend-build、acceptance 三 job 成功，artifact 可下载。

---

## 验收清单

| 验收项 | 通过标准 |
|--------|---------|
| 审计收尾 | priority=1→0.2、user_priority=0.0 保留、ENVIRONMENT 大小写不敏感 |
| CI | GitHub Actions 成功，保留 artifact |
| 契约测试 | test_api_contracts.py 覆盖主要响应结构 |
| Agent 审计 | 状态词表对齐 |
| E2E | test_e2e_learning_flow.py 跑通 |
| Demo 数据 | seed_demo_data.py 可创建演示数据 |
| 文档 | README 含验收复现 + 演示启动命令 |

## 提交拆分

| commit | 信息 | 范围 |
|--------|------|------|
| 1 | `fix(audit): close priority and environment edge cases` | Phase 0 |
| 2 | `ci: add linux acceptance script and artifacts` | Phase 1 |
| 3 | `test(contract): lock api response contracts` | Phase 2 |
| 4 | `fix(audit): align agent run status vocabulary with backend` | Phase 3 |
| 5 | `test(e2e): add learning flow and demo seed data` | Phase 4 |

## 约束

- 不重写资料解析主流程
- 不恢复 algorithmic-art
- 不删除已有测试
- 不把 mock 当成真实模型能力宣传
- 不做最终报告或 PPT
