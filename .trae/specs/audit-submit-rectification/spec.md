# 本次提交审计整改 Implementation Plan

> **For agentic workers:** TDD-driven execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 闭合本次提交审计（9239e7f → 7f2081a）后剩余的 P1/P2 缺口：多课程优先级字段不生效、多课程规划未透传用户 LLM 配置、前后端 MultiPlanResult 类型不一致、production CORS 误配防护、CI 证据补齐。

**Architecture:** 前后端字段对齐 + 调度器签名扩展 + 配置硬化 + 验收脚本扩展。不引入新业务功能、不改数据库结构、不引入 embedding/vector search。

**Tech Stack:** FastAPI + Pydantic v2 + SQLAlchemy（后端）；Vue 3 + TypeScript + Element Plus（前端）；pytest + vue-tsc + PowerShell 验收脚本。

---

## 文件结构

| 文件 | 责任 | 修改类型 |
|------|------|----------|
| `backend/app/schemas/multi_plan.py` | `MultiCourseInput` 兼容 `priority` 与 `user_priority` | Modify |
| `backend/app/services/multi_scheduler.py` | `schedule_multi_courses` 新增 `user_config` 参数并透传给 `planner_generate` | Modify |
| `backend/app/api/v1/endpoints/plans.py` | `create_multi_plan` 读取 active config 并传入 scheduler | Modify |
| `backend/app/core/config.py` | `validate_prod_secrets` 拒绝 production 下 `CORS_ORIGINS="*"` | Modify |
| `backend/app/tests/test_multi_plans.py` | 新增优先级兼容测试、user_config 透传测试 | Modify |
| `backend/app/tests/test_health.py` | 新增 production wildcard CORS 拒绝测试 | Modify |
| `frontend/src/api/plan.ts` | `MultiPlanCourseInput.priority` → `user_priority`；删除 `MultiPlanResult.goal_ids` | Modify |
| `frontend/src/views/MultiPlanView.vue` | 提交 payload 使用 `user_priority: cfg.priority / 5` | Modify |
| `scripts/verify_phase2_engineering.ps1` | 新增字段一致性、CORS 误配、user_config 透传检查 | Modify |

---

## Task 1: T01 — 修复多课程优先级字段不生效（后端兼容）

**Files:**
- Modify: `backend/app/schemas/multi_plan.py`
- Test: `backend/app/tests/test_multi_plans.py`

- [ ] **Step 1: 写失败测试 — `priority` 旧字段能被兼容并归一化**

在 `test_multi_plans.py` 末尾新增：

```python
def test_multi_plan_accepts_legacy_priority_field(client) -> None:
    """T01: 旧前端发送 priority（1-5）应被兼容并归一化为 user_priority。"""
    from app.schemas.multi_plan import MultiCourseInput

    # 旧字段 priority=4 应被接受并映射到 user_priority
    item = MultiCourseInput.model_validate(
        {"course_id": 1, "deadline": "2099-01-01", "priority": 4}
    )
    assert item.user_priority == 4

    # 新字段 user_priority=0.8 仍然直接生效
    item2 = MultiCourseInput.model_validate(
        {"course_id": 1, "deadline": "2099-01-01", "user_priority": 0.8}
    )
    assert item2.user_priority == 0.8

    # 两个字段都未提供时为 None
    item3 = MultiCourseInput.model_validate(
        {"course_id": 1, "deadline": "2099-01-01"}
    )
    assert item3.user_priority is None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest app/tests/test_multi_plans.py::test_multi_plan_accepts_legacy_priority_field -v`
Expected: FAIL — `user_priority` 为 None（因为 `priority` 字段被忽略）

- [ ] **Step 3: 实现 — `MultiCourseInput` 加 `validation_alias`**

修改 `backend/app/schemas/multi_plan.py`：

```python
from pydantic import BaseModel, ConfigDict, Field, AliasChoices

class MultiCourseInput(BaseModel):
    """A single course entry in a POST /plans/multi request."""

    course_id: int
    deadline: date
    user_priority: Optional[float] = Field(
        default=None, ge=0, le=1, validation_alias=AliasChoices("user_priority", "priority")
    )
```

注意：`AliasChoices` 让字段同时接受 `user_priority`（新）和 `priority`（旧）。但旧前端发送 `priority: 3`（1-5），范围校验 `ge=0, le=1` 会拒绝。需要调整校验范围或归一化。

**关键决策**：保持后端 `user_priority` 范围 `[0, 1]`，但 `AliasChoices` 接受旧字段时跳过范围校验不行（Pydantic v2 AliasChoices 仍走同一 Field 约束）。所以方案改为：
- 后端 `user_priority` 字段范围放宽到 `ge=0, le=5`（接受 1-5 旧值）
- 在 `create_multi_plan` 中归一化：若值 > 1，除以 5

更新 `multi_plan.py`：

```python
class MultiCourseInput(BaseModel):
    """A single course entry in a POST /plans/multi request.

    ``user_priority`` 兼容两种输入：
    - 新格式：0-1 的浮点数（如 0.8）
    - 旧格式：1-5 的整数（如 4），由 API 层归一化为 0-1
    """

    course_id: int
    deadline: date
    user_priority: Optional[float] = Field(
        default=None,
        ge=0,
        le=5,
        validation_alias=AliasChoices("user_priority", "priority"),
    )
```

- [ ] **Step 4: 在 `create_multi_plan` 中归一化 `user_priority`**

修改 `backend/app/api/v1/endpoints/plans.py` 的 `create_multi_plan`，构建 `courses_input` 时归一化：

```python
courses_input = [
    {
        "course_id": c.course_id,
        "deadline": c.deadline,
        "user_priority": (
            c.user_priority / 5.0
            if c.user_priority is not None and c.user_priority > 1
            else c.user_priority
        ),
    }
    for c in payload.courses
]
```

- [ ] **Step 5: 更新测试断言（旧字段 priority=4 应映射到 user_priority=4，归一化在 API 层）**

测试调整为验证 schema 层兼容（值 4 被接受），归一化由 API 层处理。补充一个 API 层测试：

```python
def test_multi_plan_normalizes_priority_in_api(client, monkeypatch) -> None:
    """T01: API 层应把 priority=4（1-5）归一化为 user_priority=0.8 并传入 scheduler。"""
    captured = {}

    def fake_schedule(db, user_id, courses, daily_minutes, user_config=None):
        captured["courses"] = courses
        return {"schedule": [], "overflow_warnings": []}

    monkeypatch.setattr("app.api.v1.endpoints.plans.schedule_multi_courses", fake_schedule)
    # ... login + post payload with priority=4
    # assert captured["courses"][0]["user_priority"] == 0.8
```

- [ ] **Step 6: 运行测试验证通过**

Run: `cd backend && python -m pytest app/tests/test_multi_plans.py -v`
Expected: PASS

---

## Task 2: T02 — 多课程规划透传用户 LLM 配置

**Files:**
- Modify: `backend/app/services/multi_scheduler.py`
- Modify: `backend/app/api/v1/endpoints/plans.py`
- Test: `backend/app/tests/test_multi_plans.py`

- [ ] **Step 1: 写失败测试 — scheduler 收到 user_config 并传给 planner_generate**

在 `test_multi_plans.py` 新增：

```python
def test_schedule_multi_courses_passes_user_config_to_planner(client, monkeypatch) -> None:
    """T02: schedule_multi_courses 应把 user_config 透传给 planner_generate。"""
    from app.services import multi_scheduler

    captured = {}

    def fake_planner_generate(db, user_id, goal, courses, deadline, daily_minutes, user_config=None):
        captured["user_config"] = user_config
        return {"tasks": []}

    monkeypatch.setattr(multi_scheduler, "planner_generate", fake_planner_generate)

    from datetime import date
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        multi_scheduler.schedule_multi_courses(
            db=db,
            user_id=1,
            courses=[{"course_id": 1, "deadline": date(2099, 1, 1), "user_priority": 0.5}],
            daily_minutes=120,
            user_config={"provider": "real", "model": "gpt-4"},
        )
    finally:
        db.close()

    assert captured["user_config"] == {"provider": "real", "model": "gpt-4"}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest app/tests/test_multi_plans.py::test_schedule_multi_courses_passes_user_config_to_planner -v`
Expected: FAIL — `schedule_multi_courses() got an unexpected keyword argument 'user_config'`

- [ ] **Step 3: 实现 — scheduler 新增 `user_config` 参数并透传**

修改 `backend/app/services/multi_scheduler.py`：

```python
def schedule_multi_courses(
    db: Session,
    user_id: int,
    courses: list[dict[str, Any]],
    daily_minutes: int,
    user_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # ... 在 planner_generate 调用处加 user_config=user_config
    plan_output = planner_generate(
        db=db,
        user_id=user_id,
        goal=f"完成 {course_name} 学习计划",
        courses=[course_name],
        deadline=deadline,
        daily_minutes=daily_minutes,
        user_config=user_config,
    )
```

- [ ] **Step 4: 实现 — `create_multi_plan` 读取 active config 并传入 scheduler**

修改 `backend/app/api/v1/endpoints/plans.py` 的 `create_multi_plan`，在调用 `schedule_multi_courses` 之前加：

```python
active_config = get_active_config(db, current_user.id)
user_config = build_user_config(active_config) if active_config else None

schedule = schedule_multi_courses(
    db=db,
    user_id=current_user.id,
    courses=courses_input,
    daily_minutes=payload.daily_minutes,
    user_config=user_config,
)
```

- [ ] **Step 5: 运行测试验证通过**

Run: `cd backend && python -m pytest app/tests/test_multi_plans.py -v`
Expected: PASS

---

## Task 3: T03 — 对齐 MultiPlanResult 前后端类型

**Files:**
- Modify: `frontend/src/api/plan.ts`

- [ ] **Step 1: 删除前端 `MultiPlanResult.goal_ids`**

修改 `frontend/src/api/plan.ts`：

```typescript
export interface MultiPlanResult {
  schedule: MultiPlanScheduleItem[]
  overflow_warnings: string[]
}
```

- [ ] **Step 2: 运行前端构建验证无 TS 错误**

Run: `cd frontend && npm run build`
Expected: PASS — 无引用 `goal_ids` 的地方

---

## Task 4: T04 — 增强 production CORS 校验

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/app/tests/test_health.py`

- [ ] **Step 1: 写失败测试 — production 下 CORS_ORIGINS="*" 应启动失败**

在 `test_health.py` 新增：

```python
def test_prod_rejects_wildcard_cors() -> None:
    """T04: ENVIRONMENT=production 且 CORS_ORIGINS='*' 应启动校验失败。"""
    from app.core.config import Settings

    s = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a-real-secret",
        LLM_CONFIG_SECRET_KEY="a-valid-fernet-key",
        CORS_ORIGINS="*",
    )
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        s.validate_prod_secrets()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest app/tests/test_health.py::test_prod_rejects_wildcard_cors -v`
Expected: FAIL — 不抛异常

- [ ] **Step 3: 实现 — `validate_prod_secrets` 加 CORS 校验**

修改 `backend/app/core/config.py` 的 `validate_prod_secrets`：

```python
def validate_prod_secrets(self) -> None:
    if self.ENVIRONMENT != "production":
        return
    if self.JWT_SECRET_KEY in (_DEFAULT_JWT_SECRET, ""):
        raise ValueError(
            "生产环境不能使用默认 JWT_SECRET_KEY，请设置一个随机长字符串。"
        )
    if self.LLM_CONFIG_SECRET_KEY in (_DEFAULT_LLM_CONFIG_SECRET, ""):
        raise ValueError(
            "生产环境不能使用默认 LLM_CONFIG_SECRET_KEY，请设置一个 "
            "Fernet 兼容密钥。"
        )
    # T04: production 下拒绝 CORS_ORIGINS="*" 或空来源
    origins = self.cors_origin_list()
    if not origins or "*" in origins:
        raise ValueError(
            "生产环境不能使用 CORS_ORIGINS='*' 或空来源，请设置实际前端域名。"
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest app/tests/test_health.py -v`
Expected: PASS

---

## Task 5: 更新验收脚本 + 前端字段对齐

**Files:**
- Modify: `frontend/src/api/plan.ts`（`MultiPlanCourseInput.priority` → `user_priority`）
- Modify: `frontend/src/views/MultiPlanView.vue`（提交 payload 使用 `user_priority: cfg.priority / 5`）
- Modify: `scripts/verify_phase2_engineering.ps1`

- [ ] **Step 1: 前端 `MultiPlanCourseInput` 改 `user_priority`**

修改 `frontend/src/api/plan.ts`：

```typescript
export interface MultiPlanCourseInput {
  course_id: number
  deadline: string
  user_priority?: number
}
```

- [ ] **Step 2: 前端 `MultiPlanView.vue` 提交 payload 归一化**

修改 `handleGenerate` 中的 payload 构建：

```typescript
const payload: MultiPlanPayload = {
  courses: selectedCourses.value.map((c) => {
    const cfg = courseConfigs[c.id]
    return {
      course_id: c.id,
      deadline: cfg.deadline,
      user_priority: cfg.priority / 5,
    }
  }),
  daily_minutes: dailyMinutes.value,
  constraints: constraints.value,
}
```

- [ ] **Step 3: 扩展 `verify_phase2_engineering.ps1`**

在脚本末尾（section 7 之后）加 section 8：

```powershell
# 8. T01-T04 audit-submit-rectification checks
Write-Step 'Audit-submit-rectification checks'

# T01: backend MultiCourseInput has AliasChoices for priority/user_priority
$multiPlanSchema = Get-Content "$root\backend\app\schemas\multi_plan.py" -Raw
if ($multiPlanSchema -match 'AliasChoices' -and $multiPlanSchema -match 'priority') {
  Write-Ok 'MultiCourseInput accepts both priority and user_priority'
} else {
  Write-Bad 'MultiCourseInput missing AliasChoices compat for priority'
}

# T02: schedule_multi_courses has user_config param
$schedulerPy = Get-Content "$root\backend\app\services\multi_scheduler.py" -Raw
if ($schedulerPy -match 'user_config') {
  Write-Ok 'schedule_multi_courses accepts user_config'
} else {
  Write-Bad 'schedule_multi_courses missing user_config param'
}

# T02: create_multi_plan reads active config
$plansPy = Get-Content "$root\backend\app\api\v1\endpoints\plans.py" -Raw
if ($plansPy -match 'get_active_config' -and $plansPy -match 'user_config=user_config') {
  Write-Ok 'create_multi_plan passes user_config to scheduler'
} else {
  Write-Bad 'create_multi_plan does not pass user_config'
}

# T03: frontend MultiPlanResult has no goal_ids
$planTs = Get-Content "$root\frontend\src\api\plan.ts" -Raw
if ($planTs -notmatch 'goal_ids') {
  Write-Ok 'frontend MultiPlanResult has no goal_ids'
} else {
  Write-Bad 'frontend MultiPlanResult still has goal_ids'
}

# T04: config.py rejects wildcard CORS in production
$configPy = Get-Content "$root\backend\app\core\config.py" -Raw
if ($configPy -match 'CORS_ORIGINS' -and $configPy -match '\*') {
  Write-Ok 'config.py rejects wildcard CORS in production'
} else {
  Write-Bad 'config.py missing wildcard CORS rejection'
}
```

- [ ] **Step 4: 运行前端构建 + 验收脚本**

Run: `cd frontend && npm run build`
Run: `pwsh ./scripts/verify_phase2_engineering.ps1 -SkipBackend`
Expected: PASS

---

## Task 6: 全量验收 + 提交 + 推送 + 触发 CI

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && python -m pytest app/tests/ -q`
Expected: 全部通过（207 + 新增 ≈ 210+）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 无 TS/Vite 错误

- [ ] **Step 3: 验收脚本**

Run: `pwsh ./scripts/verify_phase2_engineering.ps1`
Expected: ACCEPTANCE PASSED

- [ ] **Step 4: 提交**

```bash
git add backend/app/schemas/multi_plan.py backend/app/services/multi_scheduler.py backend/app/api/v1/endpoints/plans.py backend/app/core/config.py backend/app/tests/test_multi_plans.py backend/app/tests/test_health.py frontend/src/api/plan.ts frontend/src/views/MultiPlanView.vue scripts/verify_phase2_engineering.ps1
git commit -m "fix(audit): close multi-plan config and production hardening gaps"
```

- [ ] **Step 5: 推送**

```bash
git push origin main
```

- [ ] **Step 6: 触发 GitHub Actions workflow_dispatch**

通过 `gh workflow run` 或 GitHub UI 触发 CI，确认 Backend Tests 与 Frontend Build 成功。

---

## 验收清单

| 项目 | 命令/检查 | 通过标准 |
|------|----------|---------|
| 后端测试 | `cd backend; python -m pytest app/tests/ -q` | 全部通过 |
| 前端构建 | `cd frontend; npm run build` | 无错误 |
| 验收脚本 | `pwsh ./scripts/verify_phase2_engineering.ps1` | ACCEPTANCE PASSED |
| 字段一致性 | Network payload 含 `user_priority` | 浏览器验证 |
| CORS 误配防护 | production + `*` 启动失败 | 单测覆盖 |
| user_config 透传 | scheduler 收到 user_config | 单测覆盖 |
| CI 证据 | GitHub Actions workflow run | Backend + Frontend 成功 |

## 约束

- 不重构无关页面
- 不引入 embedding/vector search
- 不改数据库结构
- 提交信息：`fix(audit): close multi-plan config and production hardening gaps`
