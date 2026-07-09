# Material Parse-Status & Upload-Time Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two reported symptoms on the materials page: (1) after uploading a PDF the "解析中" (processing) state never completes or gets interrupted; (2) the displayed upload time does not match the real upload time (8-hour skew).

**Architecture:** Two independent root causes. (A) Frontend `customUpload` triggers parse but never awaits it, then calls `fetchMaterials()` in `.finally()` which races ahead of the backend flipping status to `processing` — so `ensurePolling()` sees no processing material and never starts polling; the UI stays "解析中" forever even though the backend already finished. Fix: await the parse request, then fetch the list so polling reliably starts. (B) The default DB is SQLite, whose SQLAlchemy dialect strips `tzinfo` from `DateTime(timezone=True)` columns on read, so the API returns naive ISO strings (no offset) and the browser's `new Date(...)` treats them as local time → 8h skew for UTC+8 clients. Fix: attach UTC `tzinfo` to naive datetimes at the Pydantic serialization boundary. Two smaller hardening fixes: stop the background parser from overwriting `parse_started_at` (resets the elapsed timer + timeout clock), and bump the parse timeout from 300s→600s so slow PDFs aren't prematurely declared timed out.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / Pydantic v2 (backend); Vue 3 + TypeScript + Element Plus + Vite (frontend); pytest (backend tests, in-memory SQLite); no frontend test runner (verify via `npm run build` + browser).

---

## Root-Cause Evidence

- **Timezone (confirmed by repro):** storing `datetime.now(timezone.utc)` (`2026-07-09T03:14:32+00:00`) into a SQLite `DateTime(timezone=True)` column and reading it back yields a **naive** datetime (`tzinfo=None`); Pydantic serializes it as `"2026-07-09T03:14:32.003001"` (no offset). `new Date("2026-07-09T03:14:32.003001")` is parsed as **local time**, so a UTC+8 user sees 03:14 instead of 11:14 — exactly the reported wrong time. After attaching UTC tzinfo, Pydantic emits `"2026-07-09T03:14:32.003001Z"` and the browser converts correctly.
- **Polling race:** [MaterialsView.vue:210](file:///f:/course-learning-agent/frontend/src/views/MaterialsView.vue#L210) calls `parseMaterial(materialId)` **without `await`**; [MaterialsView.vue:230](file:///f:/course-learning-agent/frontend/src/views/MaterialsView.vue#L230) calls `fetchMaterials()` in `.finally()` which runs before the parse request resolves, so the list still shows `status="uploaded"`, `hasProcessing()` is false, and `ensurePolling()` never starts polling. The manual `handleParse` flow ([MaterialsView.vue:248-260](file:///f:/course-learning-agent/frontend/src/views/MaterialsView.vue#L248)) works because it sets the local row to `processing` before polling — confirming the auto-parse flow is the regression.
- **Double-set of `parse_started_at`:** [parse.py:146](file:///f:/course-learning-agent/backend/app/api/v1/endpoints/parse.py#L146) sets it when the request arrives; [material_parser.py:90](file:///f:/course-learning-agent/backend/app/services/material_parser.py#L90) overwrites it when the background task starts, resetting the "已耗时 N 秒" timer and the 300s timeout clock.
- **Timeout:** [materials.py:31](file:///f:/course-learning-agent/backend/app/api/v1/endpoints/materials.py#L31) `PARSE_TIMEOUT_SECONDS = 300`. `_recover_timed_out_materials` (runs on every `list_materials`) flips a still-running parse to `failed` after 300s.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `backend/app/core/timezone.py` | UTC datetime helpers | Add `ensure_utc(dt)` helper |
| `backend/app/schemas/material.py` | Material API response schema | Add `field_validator` that attaches UTC tzinfo to naive datetimes for `uploaded_at`/`parse_started_at`/`parse_finished_at` |
| `backend/app/services/material_parser.py` | Parse retry/state machine | Only set `parse_started_at` when it is `None` (preserve endpoint's start time) |
| `backend/app/api/v1/endpoints/materials.py` | Materials list + timeout recovery | Bump `PARSE_TIMEOUT_SECONDS` 300→600 |
| `backend/app/tests/test_material_timezone.py` | NEW test | Assert API returns tz-aware ISO strings |
| `backend/app/tests/test_parse_started_at_preserved.py` | NEW test | Assert background parse preserves the endpoint's `parse_started_at` |
| `backend/app/tests/test_parse_retry_timeout.py` | Existing test | Add regression guard for the 600s default |
| `frontend/src/views/MaterialsView.vue` | Materials page | Await `parseMaterial` then `fetchMaterials` in `customUpload` so polling starts reliably |

---

### Task 1: Add `ensure_utc` helper to timezone module

**Files:**
- Modify: `backend/app/core/timezone.py`

- [ ] **Step 1: Add the helper**

Append to `backend/app/core/timezone.py` (after `utc_now`):

```python
def ensure_utc(dt: datetime | None) -> datetime | None:
    """Return ``dt`` as a timezone-aware UTC datetime, or ``None``.

    SQLite's SQLAlchemy dialect strips ``tzinfo`` from
    ``DateTime(timezone=True)`` columns on read, returning a naive
    datetime even when an aware UTC value was stored. Pydantic then
    serializes a naive datetime without an offset, and the browser's
    ``new Date("...")`` treats a no-offset ISO string as local time —
    producing an 8-hour skew for UTC+8 clients. Attaching UTC tzinfo
    here (at the serialization boundary) makes the API always emit an
    explicit offset (``+00:00`` / ``Z``) so the frontend converts
    correctly. ``None`` is passed through.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
```

- [ ] **Step 2: Sanity-check it imports**

Run: `cd backend; python -c "from app.core.timezone import ensure_utc, utc_now; from datetime import timezone; d=utc_now(); print(ensure_utc(d.replace(tzinfo=None)).tzinfo==timezone.utc)"`
Expected: prints `True`

---

### Task 2: Fix timezone serialization in `MaterialResponse` (TDD)

**Files:**
- Test: `backend/app/tests/test_material_timezone.py`
- Modify: `backend/app/schemas/material.py`

- [ ] **Step 1: Write the failing test**

Create `backend/app/tests/test_material_timezone.py`:

```python
"""Tests for timezone-aware serialization of Material timestamps.

SQLite's SQLAlchemy dialect strips tzinfo from DateTime(timezone=True)
columns on read, so the API used to emit naive ISO strings (no offset).
The browser then treated them as local time, producing an 8-hour skew
for UTC+8 clients. These tests lock in the fix: every timestamp
returned by the materials API MUST carry an explicit UTC offset.
"""
from datetime import datetime

from app.tests.conftest import auth_headers, create_course, upload_material


def _assert_tz_aware(iso_str: str) -> None:
    """A timestamp string must parse to a tz-aware datetime."""
    assert isinstance(iso_str, str), f"expected str, got {type(iso_str)}"
    dt = datetime.fromisoformat(iso_str)
    assert dt.tzinfo is not None, (
        f"timestamp must be tz-aware (have an offset), got: {iso_str!r}"
    )


def test_list_materials_returns_tz_aware_uploaded_at(client, tmp_path, monkeypatch) -> None:
    """GET /courses/{id}/materials returns uploaded_at with a UTC offset."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    upload_material(client, headers, course_id, "notes.txt", b"hello world")

    resp = client.get(f"/api/v1/courses/{course_id}/materials", headers=headers)
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    _assert_tz_aware(item["uploaded_at"])


def test_parse_response_exposes_tz_aware_parse_times(
    client, tmp_path, monkeypatch
) -> None:
    """After a parse, parse_started_at / parse_finished_at carry an offset."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client,
        headers,
        course_id,
        "notes.txt",
        ("操作系统管理硬件资源。" * 20).encode("utf-8"),
    )

    parse_resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert parse_resp.status_code == 200

    resp = client.get(f"/api/v1/courses/{course_id}/materials", headers=headers)
    item = next(m for m in resp.json()["items"] if m["id"] == material_id)
    _assert_tz_aware(item["uploaded_at"])
    # Background task runs synchronously under TestClient, so by now the
    # parse has finished and both parse timestamps are populated.
    assert item["parse_started_at"] is not None
    _assert_tz_aware(item["parse_started_at"])
    assert item["parse_finished_at"] is not None
    _assert_tz_aware(item["parse_finished_at"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend; python -m pytest app/tests/test_material_timezone.py -v`
Expected: FAIL — `assert dt.tzinfo is not None` fails because the API returns `"2026-07-09T03:14:32.003001"` (no offset).

- [ ] **Step 3: Implement the fix in `MaterialResponse`**

Edit `backend/app/schemas/material.py`. Add imports and a `field_validator`:

```python
"""Pydantic schemas for the material endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.timezone import ensure_utc


class MaterialResponse(BaseModel):
    """Material fields returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    course_id: int
    filename: str
    file_type: str
    file_path: str
    status: str
    version: int
    error_message: Optional[str] = None
    uploaded_at: datetime
    parse_started_at: Optional[datetime] = None
    parse_finished_at: Optional[datetime] = None
    parse_attempts: int = 0
    last_parse_error: Optional[str] = None

    # SQLite strips tzinfo from DateTime(timezone=True) columns on read,
    # so a datetime loaded from the DB is naive even though it was
    # stored as aware UTC. Pydantic would then serialize it without an
    # offset, and the browser's new Date(...) would treat it as local
    # time (8-hour skew for UTC+8 clients). Attach UTC tzinfo before
    # serialization so the API always emits an explicit offset.
    @field_validator(
        "uploaded_at",
        "parse_started_at",
        "parse_finished_at",
        mode="before",
    )
    @classmethod
    def _attach_utc(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return ensure_utc(value)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend; python -m pytest app/tests/test_material_timezone.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `cd backend; python -m pytest -q`
Expected: all green (340+ tests pass)

---

### Task 3: Preserve `parse_started_at` in the background parser (TDD)

**Files:**
- Test: `backend/app/tests/test_parse_started_at_preserved.py`
- Modify: `backend/app/services/material_parser.py`

- [ ] **Step 1: Write the failing test**

Create `backend/app/tests/test_parse_started_at_preserved.py`:

```python
"""parse_with_retry must NOT overwrite parse_started_at set by the endpoint.

The endpoint sets parse_started_at when the user clicks parse. The
background task used to overwrite it with utc_now() when it started,
which reset the "已耗时 N 秒" elapsed timer and the timeout clock. The
task should only set parse_started_at when it is None (defensive
fallback), preserving the original start time.
"""
from datetime import timedelta

from app.core.timezone import utc_now
from app.models.material import Material
from app.services.material_parser import parse_with_retry


def test_parse_with_retry_preserves_parse_started_at(
    db_session, sample_user, sample_course, monkeypatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", ".")
    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="notes.txt",
        file_type="txt",
        file_path="notes.txt",
        status="processing",
    )
    db_session.add(material)
    db_session.commit()

    # The endpoint set parse_started_at 10 seconds ago.
    started = utc_now() - timedelta(seconds=10)
    material.parse_started_at = started
    db_session.commit()

    captured: dict = {}

    def fake_parse(path, file_type):
        # Capture the value visible to the parse function.
        captured["started_at"] = material.parse_started_at
        return [(1, "操作系统管理硬件资源。" * 20)]

    status, count = parse_with_retry(
        db_session, material, sample_user.id, parse_fn=fake_parse
    )

    assert status == "ready"
    assert count >= 1
    # The start time set by the endpoint must survive into the parse.
    assert captured["started_at"] == started
    # And must still be the original value after parse completes.
    assert material.parse_started_at == started
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend; python -m pytest app/tests/test_parse_started_at_preserved.py -v`
Expected: FAIL — `assert captured["started_at"] == started` fails because `parse_with_retry` overwrote `parse_started_at` with `utc_now()` at line 90.

- [ ] **Step 3: Implement the fix**

Edit `backend/app/services/material_parser.py` lines 88-92. Change:

```python
    material.status = "processing"
    material.error_message = None
    material.parse_started_at = utc_now()
    material.parse_attempts = 0
    db.commit()
```

to:

```python
    material.status = "processing"
    material.error_message = None
    # Preserve the parse_started_at set by the parse endpoint so the
    # frontend elapsed timer and the timeout clock both start from when
    # the user requested the parse (not when the background task began).
    # Only set it as a defensive fallback if the endpoint never did.
    if material.parse_started_at is None:
        material.parse_started_at = utc_now()
    material.parse_attempts = 0
    db.commit()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend; python -m pytest app/tests/test_parse_started_at_preserved.py -v`
Expected: PASS

- [ ] **Step 5: Run the parse-related suite for regressions**

Run: `cd backend; python -m pytest app/tests/test_parse.py app/tests/test_parse_retry_timeout.py app/tests/test_parse_background_tasks.py app/tests/test_parse_background_session.py -q`
Expected: all pass

---

### Task 4: Bump parse timeout 300s→600s with regression guard

**Files:**
- Modify: `backend/app/api/v1/endpoints/materials.py`
- Modify: `backend/app/tests/test_parse_retry_timeout.py`

- [ ] **Step 1: Add the regression-guard test**

Append to `backend/app/tests/test_parse_retry_timeout.py` (after the existing tests):

```python
def test_default_parse_timeout_is_600_seconds() -> None:
    """The default parse timeout is 600s (generous for slow PDFs).

    Regression guard: a single textbook-chapter PDF can take longer than
    the old 300s under pypdf; declaring it timed out mid-parse flips the
    status to failed while the background task is still running. 600s
    keeps the crashed-worker recovery while avoiding false timeouts on
    large but legitimately-running parses.
    """
    from app.api.v1.endpoints import materials as materials_endpoint

    assert materials_endpoint.PARSE_TIMEOUT_SECONDS == 600
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend; python -m pytest app/tests/test_parse_retry_timeout.py::test_default_parse_timeout_is_600_seconds -v`
Expected: FAIL — `assert 300 == 600`

- [ ] **Step 3: Implement the fix**

Edit `backend/app/api/v1/endpoints/materials.py` line 31. Change:

```python
PARSE_TIMEOUT_SECONDS = 300
```

to:

```python
# 600s (was 300s): a single large PDF chapter under pypdf can run longer
# than 5 minutes; declaring it timed out mid-parse flips the status to
# ``failed`` while the background task is still running, which the user
# perceives as "解析中断". 600s keeps crashed-worker recovery while
# avoiding false timeouts on legitimately-running parses.
PARSE_TIMEOUT_SECONDS = 600
```

- [ ] **Step 4: Run the timeout tests to verify they pass**

Run: `cd backend; python -m pytest app/tests/test_parse_retry_timeout.py -v`
Expected: PASS (all tests, including the existing `test_list_materials_recovers_processing_timeout` which patches to 0, plus the new guard)

---

### Task 5: Fix frontend auto-parse polling race

**Files:**
- Modify: `frontend/src/views/MaterialsView.vue` (`customUpload`, lines 201-231)

- [ ] **Step 1: Rewrite the post-upload flow to await parse + fetch**

Edit `frontend/src/views/MaterialsView.vue`. Replace the `.then((res) => {...})` body of `customUpload` (lines 201-219) and the `.finally(...)` (lines 226-231) so the parse request is awaited and the list is fetched only after the backend has flipped the status to `processing`. Change:

```javascript
    .then((res) => {
      task.status = 'success'
      task.percent = 100
      ElMessage.success(`「${file.name}」上传成功，正在处理`)
      // Auto-parse: trigger processing immediately so the user never has
      // to click "parse" manually. The parse endpoint is a separate call
      // so upload success and parse success stay independent (a parse
      // failure does not roll back the upload).
      const materialId = res.data.id
      parseMaterial(materialId)
        .then(() => {
          ensurePolling()
        })
        .catch(() => {
          // Parse failure is surfaced via status refresh; do not block.
          fetchMaterials()
        })
      return res
    })
    .catch((err) => {
      task.status = 'error'
      task.error = parseApiError(err, '上传失败')
      ElMessage.error(`「${file.name}」上传失败：${task.error}`)
      throw err
    })
    .finally(() => {
      setTimeout(() => {
        uploadTasks.value = uploadTasks.value.filter((t) => t.uid !== task.uid)
      }, 2000)
      fetchMaterials()
    })
```

to:

```javascript
    .then(async (res) => {
      task.status = 'success'
      task.percent = 100
      ElMessage.success(`「${file.name}」上传成功，正在处理`)
      // Auto-parse: trigger processing immediately so the user never has
      // to click "parse" manually. The parse endpoint is a separate call
      // so upload success and parse success stay independent (a parse
      // failure does not roll back the upload).
      //
      // AWAIT the parse request BEFORE fetching the list: the backend
      // flips status to "processing" inside the parse endpoint, so only
      // after it resolves will listMaterials see a processing row and
      // ensurePolling() actually start polling. The old code fired
      // parseMaterial without awaiting and called fetchMaterials() in
      // .finally() which raced ahead of the status flip — so
      // hasProcessing() was false, polling never started, and the UI
      // stayed "解析中" forever even though the backend had finished.
      const materialId = res.data.id
      try {
        await parseMaterial(materialId)
      } catch {
        // Parse failure is surfaced via the status refresh below; the
        // background task writes a failed status + error log regardless.
      }
      await fetchMaterials()
      return res
    })
    .catch((err) => {
      task.status = 'error'
      task.error = parseApiError(err, '上传失败')
      ElMessage.error(`「${file.name}」上传失败：${task.error}`)
      throw err
    })
    .finally(() => {
      setTimeout(() => {
        uploadTasks.value = uploadTasks.value.filter((t) => t.uid !== task.uid)
      }, 2000)
    })
```

Note: `fetchMaterials()` is removed from `.finally()` because it now runs (always, inside the try/catch) in the awaited `.then` — keeping it in `.finally()` too would double-fetch and re-introduce the race on the upload-failure path. `fetchMaterials` already swallows its own errors.

- [ ] **Step 2: Type-check + build the frontend**

Run: `cd frontend; npm run build`
Expected: build succeeds (`vue-tsc -b` + `vite build`, no TS errors)

- [ ] **Step 3: Manual browser verification (agent-browser skill)**

Start the backend + frontend, log in, open a course's materials page, upload a small PDF/txt, and confirm:
1. The status transitions `uploaded → 解析中 → 就绪/解析失败` and does NOT get stuck on 解析中.
2. The "上传时间" column shows the current local time (not 8 hours off).
3. The "已耗时 N 秒" hint counts up from 0 while processing (no backwards jump).

---

### Task 6: Full regression + commit

**Files:** none (verification + commit only)

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend; python -m pytest -q`
Expected: all pass (340+ tests, including the 2 new tz tests, the new `parse_started_at` test, and the new timeout guard)

- [ ] **Step 2: Run the acceptance script if present**

Run: `cd f:\course-learning-agent; pwsh -File scripts/verify_phase2_engineering.ps1` (if it exists and section 16/17 are relevant)
Expected: all sections pass

- [ ] **Step 3: Rebuild the frontend**

Run: `cd frontend; npm run build`
Expected: build succeeds

- [ ] **Step 4: Commit with the git-commit skill**

Use the `git-commit` skill to stage and commit all changed files with a conventional commit message, e.g.:

```
fix(materials): repair stuck 解析中 status and 8-hour upload-time skew

- frontend: await parseMaterial before fetchMaterials in customUpload so
  ensurePolling() reliably starts (was racing the backend's status flip
  and never polling, leaving the UI stuck on 解析中)
- schemas: attach UTC tzinfo to Material timestamps before serialization;
  SQLite strips tzinfo on read so the API emitted offset-less ISO strings
  and the browser treated them as local time (8h skew for UTC+8 clients)
- material_parser: preserve parse_started_at set by the endpoint instead
  of overwriting it (was resetting the elapsed timer + timeout clock)
- materials: bump PARSE_TIMEOUT_SECONDS 300→600 so slow PDFs are not
  prematurely declared timed out while the background task is still running
```

Files to stage:
- `backend/app/core/timezone.py`
- `backend/app/schemas/material.py`
- `backend/app/services/material_parser.py`
- `backend/app/api/v1/endpoints/materials.py`
- `backend/app/tests/test_material_timezone.py`
- `backend/app/tests/test_parse_started_at_preserved.py`
- `backend/app/tests/test_parse_retry_timeout.py`
- `frontend/src/views/MaterialsView.vue`

---

## Self-Review

**1. Spec coverage:**
- "解析中 一直不会完成" → Task 5 (await parse + fetch → polling starts) is the primary fix; Task 3 (accurate elapsed timer) and Task 4 (don't prematurely time out) support it. ✓
- "或者中断" → Task 4 (600s timeout) prevents a running parse from being flipped to failed. ✓
- "显示的时间也不符合真实上传的时间" → Task 1+2 (ensure_utc + schema validator) makes `uploaded_at` (and parse times) carry a UTC offset so the browser converts to local. ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling" present. Every code step shows the actual code. ✓

**3. Type consistency:** `ensure_utc(dt)` is defined in Task 1 and consumed by `_attach_utc` in Task 2 with the same signature. `parse_with_retry`'s `parse_fn` signature `(path, file_type) -> list` matches the existing test helper and the fake in Task 3. `PARSE_TIMEOUT_SECONDS` referenced in Task 4's test matches the constant in `materials.py`. ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-09-fix-material-parse-status-time.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session, batch execution with checkpoints

Which approach?
