# 跨课程知识图谱 v3 工程收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 819da49 基础上完成 v3 收尾——证据缓存按内容版本化、旧库兼容、CI 证据归档、验收脚本行为化、user_focus 枚举约束，不扩展新功能。

**Architecture:** evidence_hash 从"仅 chunk_id"升级为"chunk_id + 内容摘要"；新增轻量启动期列迁移器（无 Alembic）保证旧 SQLite 库不崩；CI 证据写入 docs/engineering/ci_evidence.md；验收脚本新增 5 个关键 compare 行为测试的显式 pytest；CompareRequest.user_focus 用 Literal 约束为 concept/exam/transfer。

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / SQLAlchemy / pytest / PowerShell + Bash 验收脚本 / GitHub Actions CI

**基线提交:** 819da49（main 分支，CI #28914666690 已 success）

---

## File Structure

- **Modify** `backend/app/services/concept_compare_service.py` — `_compute_evidence_hash` 改为接收 evidence_chunks 列表，基于 chunk_id+material_id+course_id+page_no+title+text 计算 SHA1；`get_or_create_compare_report` 调整为"先收集 chunk_ids → 加载 evidence_chunks → 计算 hash → 查缓存"。
- **Create** `backend/app/db/migrations.py` — 轻量列迁移器 `ensure_concept_compare_report_columns(engine)`，用 SQLAlchemy inspect 检测并 ALTER TABLE 补 `user_focus`/`evidence_hash` 两列（仅 SQLite 兼容写法）。
- **Modify** `scripts/init_db.py` — 在 `create_all` 之后调用 `ensure_concept_compare_report_columns(engine)`，保证旧库启动即兼容。
- **Modify** `backend/app/schemas/concept_graph.py` — `CompareRequest.user_focus: Literal["concept","exam","transfer"]`。
- **Create** `docs/engineering/ci_evidence.md` — CI run id 28914666690、head sha 819da49、三 job success、三 artifact、Node20 deprecation 备注。
- **Modify** `scripts/verify_phase2_engineering.ps1` + `scripts/verify_phase2_engineering.sh` — 新增第 13 节，显式运行 5 个 compare 关键行为测试。
- **Modify** `backend/app/tests/test_concept_compare_agent.py` — 新增内容变更缓存失效测试 + 旧库迁移测试。
- **Create** `backend/app/tests/test_db_migrations.py` — 测试 `ensure_concept_compare_report_columns`。

---

## Task 1: evidence_hash 按证据内容计算（P0）

**Files:**
- Modify: `backend/app/services/concept_compare_service.py:79-84`（`_compute_evidence_hash`）与 `:127-129`（调用点）
- Test: `backend/app/tests/test_concept_compare_agent.py`（新增 `test_compare_cache_invalidates_when_evidence_text_changes`）

- [ ] **Step 1: 写失败测试**

在 `backend/app/tests/test_concept_compare_agent.py` 末尾追加：

```python
def test_compare_cache_invalidates_when_evidence_text_changes(db_session, monkeypatch):
    """同一 chunk_id 但文本内容变化时缓存必须失效（hash 基于内容，不只是 id）。"""
    from app.models import MaterialChunk

    user, n1, n2 = _setup_two_nodes(db_session)
    ch1 = MaterialChunk(
        material_id=1, course_id=n1.course_id, chunk_index=0,
        title="证据1", page_no=1, text="原始内容A",
    )
    db_session.add(ch1)
    db_session.commit()
    n1.source_chunk_ids = json.dumps([ch1.id])
    db_session.commit()

    call_count = {"n": 0}

    def fake_generate(db, uid, concept_a, concept_b, evidence_chunks=None,
                      user_config=None, user_focus="concept"):
        call_count["n"] += 1
        return {
            "report_json": {"concept_a": {}, "concept_b": {}, "similarities": []},
            "citation_chunk_ids": [],
            "provider": "mock", "model_name": "mock",
            "fallback_used": False, "fallback_reason": "", "audit_run_id": 1,
        }

    monkeypatch.setattr(
        "app.services.concept_compare_service.generate_compare", fake_generate
    )
    # 第一次：原文
    get_or_create_compare_report(db_session, user.id, n1.id, n2.id)
    # 改文本，chunk_id 不变
    ch1.text = "修改后的内容B"
    db_session.commit()
    # 第二次：内容变了，hash 应不同，必须重新生成
    get_or_create_compare_report(db_session, user.id, n1.id, n2.id)
    reports = db_session.query(ConceptCompareReport).all()
    assert len(reports) == 2, "证据内容变化（同 chunk_id）必须使缓存失效"
    assert call_count["n"] == 2
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py::test_compare_cache_invalidates_when_evidence_text_changes -v`
Expected: FAIL — `assert 1 == 2`（当前 hash 仅依赖 chunk_id，文本变了仍命中缓存）

- [ ] **Step 3: 实现 — 改 `_compute_evidence_hash` 签名与逻辑**

把 `backend/app/services/concept_compare_service.py` 的 `_compute_evidence_hash` 替换为：

```python
def _compute_evidence_hash(evidence_chunks: list[dict]) -> str:
    """SHA1 of evidence content (chunk_id + material_id + course_id + page_no + title + text), truncated to 16 chars.

    基于内容而非仅 chunk_id，保证同 chunk_id 文本变化时缓存失效。
    """
    if not evidence_chunks:
        return ""
    parts: list[str] = []
    for c in sorted(evidence_chunks, key=lambda x: x.get("chunk_id", 0)):
        parts.append(
            f"{c.get('chunk_id', '')}|{c.get('material_id', '')}|"
            f"{c.get('course_id', '')}|{c.get('page_no', '')}|"
            f"{c.get('title', '')}|{c.get('text', '')}"
        )
    payload = "\n".join(parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: 实现 — 调整 `get_or_create_compare_report` 调用顺序**

把 `get_or_create_compare_report` 中"先收集 chunk_ids → 计算 hash → 查缓存 → 加载 evidence_chunks"改为"先收集 chunk_ids → 加载 evidence_chunks → 计算 hash → 查缓存"。

定位当前这段（约 127-149 行）：

```python
    # Collect evidence chunk ids up front so the cache key can include them.
    chunk_ids = _collect_chunk_ids(n1, n2, edge)
    evidence_hash = _compute_evidence_hash(chunk_ids)

    # Cache lookup: same user + same node pair (either order)
    # + same user_focus + same evidence_hash.
    cached = db.query(ConceptCompareReport).filter_by(
        user_id=user_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        user_focus=user_focus,
        evidence_hash=evidence_hash,
    ).first()
    if cached is None:
        cached = db.query(ConceptCompareReport).filter_by(
            user_id=user_id,
            source_node_id=target_node_id,
            target_node_id=source_node_id,
            user_focus=user_focus,
            evidence_hash=evidence_hash,
        ).first()
    if cached is not None:
        return _report_to_dict(cached)

    # Load evidence chunks from nodes and edge.
    evidence_chunks = _load_evidence_chunks(db, user_id, chunk_ids)
```

替换为：

```python
    # Collect evidence chunk ids, load their content, then compute a
    # content-aware hash so cache invalidates when text changes (not just
    # when chunk ids change).
    chunk_ids = _collect_chunk_ids(n1, n2, edge)
    evidence_chunks = _load_evidence_chunks(db, user_id, chunk_ids)
    evidence_hash = _compute_evidence_hash(evidence_chunks)

    # Cache lookup: same user + same node pair (either order)
    # + same user_focus + same evidence_hash.
    cached = db.query(ConceptCompareReport).filter_by(
        user_id=user_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        user_focus=user_focus,
        evidence_hash=evidence_hash,
    ).first()
    if cached is None:
        cached = db.query(ConceptCompareReport).filter_by(
            user_id=user_id,
            source_node_id=target_node_id,
            target_node_id=source_node_id,
            user_focus=user_focus,
            evidence_hash=evidence_hash,
        ).first()
    if cached is not None:
        return _report_to_dict(cached)
```

并删除下方重复的 `evidence_chunks = _load_evidence_chunks(...)` 行（原 152 行附近，已被上移）。

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py -v`
Expected: PASS — 全部（含新增 + 既有 14 个）

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/concept_compare_service.py backend/app/tests/test_concept_compare_agent.py
git commit -m "fix(compare): evidence_hash based on chunk content not just chunk_id"
```

---

## Task 2: 旧库列迁移器（P0）

**Files:**
- Create: `backend/app/db/__init__.py`（空文件，声明包）
- Create: `backend/app/db/migrations.py`
- Modify: `scripts/init_db.py`
- Test: `backend/app/tests/test_db_migrations.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/app/tests/test_db_migrations.py`：

```python
"""Tests for the lightweight column migrator (no Alembic)."""
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect

from app.db.migrations import ensure_concept_compare_report_columns


def _make_old_reports_table(engine):
    """Create concept_compare_reports WITHOUT user_focus/evidence_hash."""
    metadata = MetaData()
    Table(
        "concept_compare_reports", metadata,
        Column("id", Integer, primary_key=True),
        Column("user_id", Integer),
        Column("source_node_id", Integer),
        Column("target_node_id", Integer),
        Column("report_json", String),
    )
    metadata.create_all(engine)


def test_ensure_columns_adds_missing_user_focus_and_evidence_hash():
    """旧库缺少两列时，迁移器必须补上。"""
    engine = create_engine("sqlite:///:memory:")
    _make_old_reports_table(engine)
    insp = inspect(engine)
    cols_before = {c["name"] for c in insp.get_columns("concept_compare_reports")}
    assert "user_focus" not in cols_before
    assert "evidence_hash" not in cols_before

    ensure_concept_compare_report_columns(engine)

    insp = inspect(engine)
    cols_after = {c["name"] for c in insp.get_columns("concept_compare_reports")}
    assert "user_focus" in cols_after
    assert "evidence_hash" in cols_after


def test_ensure_columns_idempotent_when_columns_already_present():
    """新库已有两列时，迁移器不得报错。"""
    from app.models.base import Base
    from app.models.concept_graph import ConceptCompareReport  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ConceptCompareReport.__table__])

    # 不应抛异常
    ensure_concept_compare_report_columns(engine)
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("concept_compare_reports")}
    assert "user_focus" in cols
    assert "evidence_hash" in cols


def test_ensure_columns_skips_when_table_absent():
    """表不存在时迁移器静默跳过（create_all 会后续建表）。"""
    engine = create_engine("sqlite:///:memory:")
    # 不建任何表，不应抛异常
    ensure_concept_compare_report_columns(engine)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && python -m pytest app/tests/test_db_migrations.py -v`
Expected: FAIL — `ModuleNotFoundError: app.db.migrations`

- [ ] **Step 3: 实现 — 创建迁移器**

创建 `backend/app/db/__init__.py`（空文件）。

创建 `backend/app/db/migrations.py`：

```python
"""Lightweight column migrations for legacy SQLite databases (no Alembic).

Project uses ``Base.metadata.create_all`` which creates new columns on
fresh DBs but does NOT alter existing tables. This module adds the
``user_focus`` / ``evidence_hash`` columns to ``concept_compare_reports``
when they are missing on an existing dev database, so old local DBs do
not crash with a 500 on compare-report insert.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {
    "user_focus": "VARCHAR(50) DEFAULT 'concept' NOT NULL",
    "evidence_hash": "VARCHAR(64) DEFAULT '' NOT NULL",
}


def ensure_concept_compare_report_columns(engine: Engine) -> None:
    """Add user_focus/evidence_hash to concept_compare_reports if missing.

    Safe to call on: fresh DB (table absent → skipped), legacy DB (table
    present, columns absent → ALTER ADD), modern DB (columns present → no-op).
    """
    insp = inspect(engine)
    if "concept_compare_reports" not in insp.get_table_names():
        return

    existing = {c["name"] for c in insp.get_columns("concept_compare_reports")}
    with engine.begin() as conn:
        for col, ddl in _REQUIRED_COLUMNS.items():
            if col not in existing:
                logger.info("adding column %s to concept_compare_reports", col)
                conn.execute(
                    text(
                        f"ALTER TABLE concept_compare_reports "
                        f"ADD COLUMN {col} {ddl}"
                    )
                )
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && python -m pytest app/tests/test_db_migrations.py -v`
Expected: PASS — 3 passed

- [ ] **Step 5: 实现 — init_db.py 调用迁移器**

修改 `scripts/init_db.py`，在 `Base.metadata.create_all(bind=engine)` 之后调用迁移器。把 `init_db()` 改为：

```python
def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # Legacy-DB compat: add user_focus/evidence_hash to existing
    # concept_compare_reports tables that predate v3. create_all does not
    # alter existing tables, so we patch them explicitly.
    from app.db.migrations import ensure_concept_compare_report_columns

    ensure_concept_compare_report_columns(engine)
    print("数据库表已创建（如已存在则跳过）。")
```

- [ ] **Step 6: 冒烟测试 — 运行 init_db + 全量测试**

Run:
```
cd backend
python ../scripts/init_db.py
python -m pytest app/tests/test_db_migrations.py app/tests/test_concept_compare_agent.py -v
```
Expected: init_db 打印"数据库表已创建"，测试全 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/__init__.py backend/app/db/migrations.py backend/app/tests/test_db_migrations.py scripts/init_db.py
git commit -m "feat(db): lightweight column migrator for legacy compare_reports tables"
```

---

## Task 3: CI 证据归档文档（P1）

**Files:**
- Create: `docs/engineering/ci_evidence.md`

> 说明：本文件由 v3 计划 5.3 节明确要求创建，非主动生成。

- [ ] **Step 1: 创建文档**

创建 `docs/engineering/ci_evidence.md`：

```markdown
# CI 工程证据

本文件归档跨课程知识图谱 v3 收尾阶段的 GitHub Actions CI 证据，作为工程交付闭环的一部分。

## 基线 CI 运行

| 项目 | 值 |
|------|----|
| Workflow | CI |
| Run ID | 28914666690 |
| 触发方式 | push |
| 分支 | main |
| Head SHA | 819da49f59633c631f45e0f117df638ff55b2cc8 |
| 触发提交 | chore(graph): add v2 audit remediation acceptance checks |
| 开始时间 | 2026-07-08 03:10:52 UTC |
| 结束时间 | 2026-07-08 03:16:07 UTC |
| 总耗时 | 约 5m15s |
| 结论 | success |

查看链接: https://github.com/dddd2024/course-learning-agent/actions/runs/28914666690

## Jobs

| Job | 结论 | 耗时 |
|-----|------|------|
| Backend Tests | success | 2m24s |
| Frontend Build | success | 19s |
| Acceptance Script | success | 2m44s |

三个 job 顺序为：Backend Tests 与 Frontend Build 并行；Acceptance Script 依赖前两者完成后运行。

## Artifacts

每个 job 均通过 `actions/upload-artifact@v4` 上传结果（`if: always()`），即使失败也保留证据。

| Artifact 名 | 来源 job | 内容 |
|-------------|----------|------|
| backend-test-result | Backend Tests | `pytest app/tests/ -v` 完整输出（271 passed） |
| frontend-build-result | Frontend Build | `npm run build` 输出 |
| acceptance-result | Acceptance Script | `verify_phase2_engineering.sh` 输出（ACCEPTANCE PASSED） |

## 已知备注

- **Node.js 20 deprecation warning**：`actions/checkout@v4`、`actions/setup-node@v4`、`actions/setup-python@v5`、`actions/upload-artifact@v4` 目标 Node.js 20，被强制运行于 Node.js 24。当前不影响 CI 通过，列为后续依赖升级项。
- CI workflow 已配置 `workflow_dispatch` 触发器，可手动重跑。

## 验证命令

本地复验 CI 证据：

```bash
gh run view 28914666690 --json status,conclusion,jobs
gh api repos/dddd2024/course-learning-agent/actions/runs/28914666690/artifacts \
  --jq '.artifacts[] | {name, size: .size_in_bytes}'
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/engineering/ci_evidence.md
git commit -m "docs(engineering): archive CI evidence for v3 closure baseline"
```

---

## Task 4: user_focus 枚举约束（P2）

**Files:**
- Modify: `backend/app/schemas/concept_graph.py:50-54`（`CompareRequest`）
- Test: `backend/app/tests/test_concept_graph_api.py`（新增 `test_compare_invalid_user_focus_returns_422`）

- [ ] **Step 1: 写失败测试**

在 `backend/app/tests/test_concept_graph_api.py` 末尾追加：

```python
def test_compare_invalid_user_focus_returns_422(client):
    """非法 user_focus 必须返回 422 校验错误，且不产生 compare report 缓存。"""
    from app.api.deps import get_db
    from app.models import ConceptCompareReport
    from app.main import app
    from sqlalchemy.orm import Session

    headers = auth_headers(client, username="alice")
    _setup_two_courses_with_kps(client, headers)
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    graph = client.get("/api/v1/concept-graph", headers=headers).json()
    edge = graph["edges"][0]

    resp = client.post(
        "/api/v1/concept-graph/compare", headers=headers,
        json={
            "source_node_id": edge["source_node_id"],
            "target_node_id": edge["target_node_id"],
            "edge_id": edge["id"],
            "user_focus": "invalid_focus",
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"

    # 不得产生缓存行
    db_gen = app.dependency_overrides[get_db]()
    db: Session = next(db_gen)
    try:
        assert db.query(ConceptCompareReport).count() == 0
    finally:
        db.close()
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && python -m pytest app/tests/test_concept_graph_api.py::test_compare_invalid_user_focus_returns_422 -v`
Expected: FAIL — 当前 `user_focus: str` 不校验枚举，请求会 200 并生成缓存

- [ ] **Step 3: 实现 — CompareRequest.user_focus 改 Literal**

修改 `backend/app/schemas/concept_graph.py`，在文件顶部 import 区加 `from typing import Literal`，并把 `CompareRequest` 改为：

```python
class CompareRequest(BaseModel):
    source_node_id: int
    target_node_id: int
    edge_id: int | None = None
    user_focus: Literal["concept", "exam", "transfer"] = "concept"
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && python -m pytest app/tests/test_concept_graph_api.py -v`
Expected: PASS — 全部（含新增）

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/concept_graph.py backend/app/tests/test_concept_graph_api.py
git commit -m "feat(compare): constrain user_focus to concept/exam/transfer enum"
```

---

## Task 5: 验收脚本行为化补强（P1）

**Files:**
- Modify: `scripts/verify_phase2_engineering.ps1`
- Modify: `scripts/verify_phase2_engineering.sh`

- [ ] **Step 1: 修改 PowerShell 脚本**

在 `scripts/verify_phase2_engineering.ps1` 的第 12 节（v2 audit remediation checks）之后、`Write-Host ''` 之前插入第 13 节：

```powershell
# 13. P3: v3 收尾 — compare 关键行为测试显式运行
Write-Step 'v3 compare behavior tests'
Push-Location "$root\backend"
& ".\.venv\Scripts\python.exe" -m pytest `
    app/tests/test_concept_compare_agent.py::test_concept_compare_mock_returns_citations_when_evidence_given `
    app/tests/test_concept_compare_agent.py::test_compare_prompt_contains_user_focus `
    app/tests/test_concept_compare_agent.py::test_compare_cache_separates_user_focus `
    app/tests/test_concept_compare_agent.py::test_compare_cache_invalidates_when_evidence_changes `
    app/tests/test_concept_compare_agent.py::test_compare_cache_invalidates_when_evidence_text_changes `
    app/tests/test_concept_compare_agent.py::test_compare_rejects_mismatched_edge_id `
    app/tests/test_concept_graph_api.py::test_compare_mismatched_edge_returns_400 `
    app/tests/test_concept_graph_api.py::test_compare_invalid_user_focus_returns_422 `
    app/tests/test_db_migrations.py `
    -q
if ($LASTEXITCODE -eq 0) { Write-Ok 'v3 compare behavior tests passed' } else { Write-Bad 'v3 compare behavior tests failed' }
Pop-Location
```

- [ ] **Step 2: 修改 Bash 脚本**

在 `scripts/verify_phase2_engineering.sh` 的第 12 节之后、`echo ""` 之前插入第 13 节：

```bash
# 13. P3: v3 closure - compare behavior tests run explicitly
step "v3 compare behavior tests"
cd "$root/backend"
if python -m pytest \
    app/tests/test_concept_compare_agent.py::test_concept_compare_mock_returns_citations_when_evidence_given \
    app/tests/test_concept_compare_agent.py::test_compare_prompt_contains_user_focus \
    app/tests/test_concept_compare_agent.py::test_compare_cache_separates_user_focus \
    app/tests/test_concept_compare_agent.py::test_compare_cache_invalidates_when_evidence_changes \
    app/tests/test_concept_compare_agent.py::test_compare_cache_invalidates_when_evidence_text_changes \
    app/tests/test_concept_compare_agent.py::test_compare_rejects_mismatched_edge_id \
    app/tests/test_concept_graph_api.py::test_compare_mismatched_edge_returns_400 \
    app/tests/test_concept_graph_api.py::test_compare_invalid_user_focus_returns_422 \
    app/tests/test_db_migrations.py \
    -q; then
  ok "v3 compare behavior tests passed"
else
  bad "v3 compare behavior tests failed"
fi
cd "$root"
```

- [ ] **Step 3: 运行验收脚本（SkipBackend 节省时间，仅验证新节）**

Run: `cd f:\course-learning-agent && pwsh -NoProfile -File ./scripts/verify_phase2_engineering.ps1 -SkipBackend`
Expected: 末尾 `ACCEPTANCE PASSED`，第 13 节 `[OK] v3 compare behavior tests passed`

- [ ] **Step 4: Commit**

```bash
git add scripts/verify_phase2_engineering.ps1 scripts/verify_phase2_engineering.sh
git commit -m "chore(verify): run v3 compare behavior tests explicitly in acceptance"
```

---

## Task 6: 全量验证 + 推送 + CI + artifacts

**Files:** 无（验证 + 推送）

- [ ] **Step 1: 全量后端测试**

Run: `cd backend && python -m pytest app/tests/ -q`
Expected: 全部 PASS（基线 271 + 新增约 4 = 275+）

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npm run build`
Expected: `✓ built` 无错误

- [ ] **Step 3: 全量验收脚本**

Run: `cd f:\course-learning-agent && pwsh -NoProfile -File ./scripts/verify_phase2_engineering.ps1`
Expected: `ACCEPTANCE PASSED`

- [ ] **Step 4: 推送**

Run: `git push origin main`
Expected: 推送成功

- [ ] **Step 5: 等待 CI 完成**

Run: `gh run watch <new_run_id> --exit-status`
Expected: 三个 job 全 success

- [ ] **Step 6: 验证 artifacts 存在**

Run:
```
gh run view <new_run_id> --json status,conclusion,jobs
gh api repos/dddd2024/course-learning-agent/actions/runs/<new_run_id>/artifacts --jq ".artifacts[] | {name, size: .size_in_bytes}"
```
Expected: status=completed, conclusion=success, 三个 artifact 均存在

- [ ] **Step 7: 把新 CI run id 追加到 ci_evidence.md**

在 `docs/engineering/ci_evidence.md` 末尾追加一节 `## v3 收尾 CI 运行`，记录新 run id、head sha、job 结论、artifacts。Commit:

```bash
git add docs/engineering/ci_evidence.md
git commit -m "docs(engineering): archive v3 closure CI run"
git push origin main
```

---

## Self-Review

**1. Spec coverage:**
- 5.1 P0 evidence_hash 内容化 → Task 1 ✓
- 5.2 P0 旧库兼容 → Task 2（轻量迁移器，init_db 调用，三选一之"启动兼容"）✓
- 5.3 P1 CI 证据文档 → Task 3 ✓
- 5.4 P1 验收脚本行为化 → Task 5 ✓
- 5.5 P2 user_focus 枚举 → Task 4 ✓
- 完成标准（pytest/build/验收/CI/artifacts/文档）→ Task 6 ✓

**2. Placeholder scan:** 无 TBD/TODO/“类似 Task N”；每步含完整代码或命令。

**3. Type consistency:**
- `_compute_evidence_hash(evidence_chunks: list[dict])` — Task 1 定义，Task 5 测试引用的 service 行为一致。
- `ensure_concept_compare_report_columns(engine: Engine)` — Task 2 定义，init_db 调用，Task 5 验收脚本运行 `test_db_migrations.py`。
- `CompareRequest.user_focus: Literal[...]` — Task 4 定义，Task 5 验收脚本运行 `test_compare_invalid_user_focus_returns_422`。
- 测试名在 Task 5 脚本中与 Task 1/2/4 定义完全一致。

无 gap。
