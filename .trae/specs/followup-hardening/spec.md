# 后续工程补强 Implementation Plan

> **For agentic workers:** TDD-driven execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 闭合后续工程补强：修复 Agent 审计检索证据展示字段错位（P0）、统一 demo seed 入口（P0）、补 Agent 审计接口契约测试（P1）、强化验收脚本（P1）、触发可见 CI 证据（P0）。

**Architecture:** 前端 extractChunks 增强支持 `output_data.items` 结构；根目录 seed 脚本改为 backend 版的薄 wrapper；新增 Agent 审计契约测试锁定 `/agent-runs` 响应结构；验收脚本加入指定测试文件运行；CI 触发后确认 artifacts。

**Tech Stack:** Vue 3 + TypeScript + Element Plus（前端）；FastAPI + Pydantic v2 + SQLAlchemy（后端）；pytest + vue-tsc + PowerShell/bash 验收脚本；GitHub Actions CI。

---

## 文件结构

| 文件 | 责任 | 修改类型 |
|------|------|----------|
| `frontend/src/views/AgentRunsView.vue` | `extractChunks` 支持 items/chunks/数组/字符串 | Modify |
| `scripts/seed_demo_data.py` | 改为 backend 版的薄 wrapper | Modify |
| `backend/app/tests/test_api_contracts.py` | 新增 Agent 审计接口契约测试 | Modify |
| `scripts/verify_phase2_engineering.ps1` | 加入指定测试文件运行 | Modify |
| `scripts/verify_phase2_engineering.sh` | 加入指定测试文件运行 | Modify |
| `README.md` | 统一 demo seed 启动说明 | Modify |

---

## Task 1: T0-1 — 修复 Agent 审计检索证据展示

**问题**：真实 chat retrieve step 的 `output_data` 是 `{ total, items }` 结构，但 `extractChunks` 只读取 `output_data.chunks` 或数组，导致检索证据不显示。

**Files:**
- Modify: `frontend/src/views/AgentRunsView.vue`

- [ ] **Step 1: 实现 `normalizeChunk` + 增强 `extractChunks`**

修改 `frontend/src/views/AgentRunsView.vue` 的 `extractChunks` 函数（行 73-81），替换为：

```typescript
function normalizeChunk(value: unknown): RetrievedChunk {
  if (typeof value === 'string') return { snippet: value }
  if (value && typeof value === 'object') return value as RetrievedChunk
  return { snippet: String(value ?? '') }
}

function extractChunks(step: AgentStep): RetrievedChunk[] {
  const out = step.output_data
  if (!out) return []
  if (Array.isArray(out)) return out.map(normalizeChunk)
  if (typeof out === 'object') {
    const obj = out as Record<string, unknown>
    // T0-1: 真实 chat retrieve step 写入 { total, items } 结构，
    // 旧 seed 写入 { chunks } 结构，两种都要支持。
    if (Array.isArray(obj.items)) return obj.items.map(normalizeChunk)
    if (Array.isArray(obj.chunks)) return obj.chunks.map(normalizeChunk)
  }
  return []
}
```

- [ ] **Step 2: 运行前端构建验证无 TS 错误**

Run: `cd frontend && npm run build`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/AgentRunsView.vue
git commit -m "fix(audit): show retrieve evidence from output_data.items"
```

---

## Task 2: T0-2 — 统一 demo seed 入口

**问题**：根目录 `scripts/seed_demo_data.py` 与 `backend/scripts/seed_demo_data.py` 是两套实现，账号密码和数据完整度不一致。backend 版是完整实现（demo/demo123456），根目录版是旧实现（demo/demo123）。

**Files:**
- Modify: `scripts/seed_demo_data.py`

- [ ] **Step 1: 根目录脚本改为薄 wrapper**

替换 `scripts/seed_demo_data.py` 全部内容为：

```python
"""Thin wrapper that delegates to backend/scripts/seed_demo_data.py.

T0-2: 项目只有一套 demo seed 实现（backend/scripts/seed_demo_data.py，
账号 demo / demo123456），根目录脚本仅做转发，方便从项目根目录执行。
"""
import runpy
from pathlib import Path

target = (
    Path(__file__).resolve().parent.parent
    / "backend"
    / "scripts"
    / "seed_demo_data.py"
)
runpy.run_path(str(target), run_name="__main__")
```

- [ ] **Step 2: README 统一 demo seed 启动说明**

修改 `README.md` 的"演示数据"区块，确保账号为 `demo / demo123456`：

```markdown
## 演示数据

一键导入演示数据（demo 用户 demo123456、操作系统/数据库课程、示例资料、
chunks、知识点、计划、待办、测验、对话、AgentRun）：

```bash
cd backend
python -m app.core.database        # 初始化表（如已有可跳过）
python ../scripts/seed_demo_data.py
```

启动后端后用 `demo / demo123456` 登录即可看到预置课程、资料、
知识点、计划、测验、对话和 Agent 审计记录。
```

- [ ] **Step 3: 提交**

```bash
git add scripts/seed_demo_data.py README.md
git commit -m "fix(seed): unify demo seed entry to backend implementation"
```

---

## Task 3: T1-2 — Agent 审计接口契约测试

**Files:**
- Modify: `backend/app/tests/test_api_contracts.py`

- [ ] **Step 1: 在 test_api_contracts.py 末尾新增 Agent 审计契约测试**

```python
# ---------------------------------------------------------------------------
# Agent audit (agent-runs) contract
# ---------------------------------------------------------------------------


def test_agent_runs_list_contract(client) -> None:
    """GET /agent-runs 返回 {items: [...], total: int}。"""
    headers = auth_headers(client, username="alice")
    # 先触发一次 chat 产生 AgentRun 记录
    course_id = create_course(client, headers, name="审计契约课程")
    material_id = upload_material(
        client, headers, course_id, "note.txt",
        "进程是程序运行的过程\n".encode("utf-8"),
    )
    client.post(f"/api/v1/materials/{material_id}/parse", headers=headers)
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "审计契约对话"},
        headers=headers,
    )
    conversation_id = conv_resp.json()["id"]
    client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是进程？",
        },
        headers=headers,
    )

    resp = client.get("/api/v1/agent-runs", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) >= {"items", "total"}
    assert isinstance(body["items"], list)
    assert isinstance(body["total"], int)
    assert body["total"] >= 1
    # 每个 item 的字段
    for item in body["items"]:
        assert set(item.keys()) >= {
            "id", "user_id", "run_type", "status",
            "input_summary", "output_summary", "duration_ms",
        }


def test_agent_runs_detail_contract(client) -> None:
    """GET /agent-runs/{id} 返回含 steps 的详情，step 有 input_data/output_data。"""
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="审计详情课程")
    material_id = upload_material(
        client, headers, course_id, "note.txt",
        "线程是进程内的执行单元\n".encode("utf-8"),
    )
    client.post(f"/api/v1/materials/{material_id}/parse", headers=headers)
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "审计详情对话"},
        headers=headers,
    )
    conversation_id = conv_resp.json()["id"]
    client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是线程？",
        },
        headers=headers,
    )

    list_resp = client.get("/api/v1/agent-runs", headers=headers)
    run_id = list_resp.json()["items"][0]["id"]

    resp = client.get(f"/api/v1/agent-runs/{run_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) >= {"id", "run_type", "status", "steps"}
    assert isinstance(body["steps"], list)
    # step 字段
    for step in body["steps"]:
        assert set(step.keys()) >= {
            "id", "run_id", "step_name", "step_index",
            "input_data", "output_data", "status",
        }


def test_agent_runs_isolation_contract(client) -> None:
    """非本人 run 访问返回 404（不泄漏存在性）。"""
    headers_a = auth_headers(client, username="alice", email="a@x.com")
    headers_b = auth_headers(client, username="bob", email="b@x.com")

    course_id = create_course(client, headers_a, name="隔离课程")
    material_id = upload_material(
        client, headers_a, course_id, "note.txt",
        "进程是程序运行的过程\n".encode("utf-8"),
    )
    client.post(f"/api/v1/materials/{material_id}/parse", headers=headers_a)
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "隔离对话"},
        headers=headers_a,
    )
    conversation_id = conv_resp.json()["id"]
    client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是进程？",
        },
        headers=headers_a,
    )

    list_resp = client.get("/api/v1/agent-runs", headers=headers_a)
    run_id = list_resp.json()["items"][0]["id"]

    # bob 不能访问 alice 的 run
    resp = client.get(f"/api/v1/agent-runs/{run_id}", headers=headers_b)
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "NOT_FOUND"
```

- [ ] **Step 2: 运行测试验证通过**

Run: `cd backend && python -m pytest app/tests/test_api_contracts.py -v`
Expected: PASS（9 个测试：原 6 + 新 3）

- [ ] **Step 3: 提交**

```bash
git add backend/app/tests/test_api_contracts.py
git commit -m "test(contract): lock agent-runs response contracts"
```

---

## Task 4: T1-1 — 强化验收脚本（指定测试文件运行）

**Files:**
- Modify: `scripts/verify_phase2_engineering.ps1`
- Modify: `scripts/verify_phase2_engineering.sh`

- [ ] **Step 1: PowerShell 脚本加入指定测试文件运行**

在 `scripts/verify_phase2_engineering.ps1` 的 section 1（Backend pytest）之后，新增 section 1b：

```powershell
# 1b. T1-1: 指定关键测试文件运行（不只做字符串检查）
Write-Step 'Key backend test files'
Push-Location "$root\backend"
& ".\.venv\Scripts\python.exe" -m pytest `
    app/tests/test_multi_plans.py `
    app/tests/test_api_contracts.py `
    app/tests/test_e2e_learning_flow.py `
    app/tests/test_health.py `
    -q
if ($LASTEXITCODE -eq 0) { Write-Ok 'key backend test files passed' } else { Write-Bad 'key backend test files failed' }
Pop-Location
```

- [ ] **Step 2: bash 脚本加入指定测试文件运行**

在 `scripts/verify_phase2_engineering.sh` 的 section 1（Backend pytest）之后，新增 section 1b：

```bash
# 1b. T1-1: 指定关键测试文件运行
step "Key backend test files"
cd "$root/backend"
if python -m pytest app/tests/test_multi_plans.py app/tests/test_api_contracts.py app/tests/test_e2e_learning_flow.py app/tests/test_health.py -q; then
  ok "key backend test files passed"
else
  bad "key backend test files failed"
fi
cd "$root"
```

- [ ] **Step 3: 运行验收脚本验证通过**

Run: `pwsh ./scripts/verify_phase2_engineering.ps1 -SkipBackend`
Expected: ACCEPTANCE PASSED

- [ ] **Step 4: 提交**

```bash
git add scripts/verify_phase2_engineering.ps1 scripts/verify_phase2_engineering.sh
git commit -m "ci: run key test files in acceptance script"
```

---

## Task 5: T0-3 — 全量验收 + 推送 + 触发 CI

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && python -m pytest app/tests/ -q`
Expected: 全部通过（226+）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: 无错误

- [ ] **Step 3: Windows 验收脚本**

Run: `pwsh ./scripts/verify_phase2_engineering.ps1`
Expected: ACCEPTANCE PASSED

- [ ] **Step 4: 推送**

```bash
git push origin main
```

- [ ] **Step 5: 触发 CI 并验证 artifact**

```bash
gh workflow run CI --ref main
```
确认 Backend Tests、Frontend Build、Acceptance Script 三 job 成功，artifact 可下载。

---

## 验收清单

| 验收项 | 通过标准 |
|--------|---------|
| Agent 审计检索证据 | 真实 chat retrieve step 能展示 output_data.items |
| Demo seed 统一 | 只有一套 demo 账号 demo/demo123456 |
| Agent 审计契约测试 | /agent-runs 与 /agent-runs/{id} 被测试锁定 |
| 验收脚本强化 | 运行指定关键测试文件 |
| CI 证据 | GitHub Actions 三 job 成功 + artifacts |
| 文档一致 | README 与脚本启动说明一致 |

## 提交拆分

| commit | 信息 | 范围 |
|--------|------|------|
| 1 | `fix(audit): show retrieve evidence from output_data.items` | T0-1 |
| 2 | `fix(seed): unify demo seed entry to backend implementation` | T0-2 |
| 3 | `test(contract): lock agent-runs response contracts` | T1-2 |
| 4 | `ci: run key test files in acceptance script` | T1-1 |
| 5 | 推送 + 触发 CI | T0-3 |

## 约束

- 不引入真正向量数据库
- 不重构整个 Agent 框架
- 不改最终报告、PPT 或无关文档
- 不删除已有后端完整 seed 数据能力
- 不把 mock fallback 伪装成真实模型结果
