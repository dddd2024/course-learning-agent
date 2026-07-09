# Fix Stuck "解析中" with NULL parse_started_at Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix materials permanently stuck in "processing" (解析中) status when `parse_started_at` is NULL — the timeout recovery logic skips them, creating an unrecoverable dead-end state.

**Architecture:** The `_recover_timed_out_materials` function filters `Material.parse_started_at.isnot(None)`, so any material stuck in "processing" with a NULL `parse_started_at` (from a legacy code path or server crash before the parse-tracking columns existed) is never recovered. Fix: use `func.coalesce(parse_started_at, updated_at)` as the timestamp for the timeout comparison, so NULL-started materials fall back to `updated_at` (always set via `TimestampMixin.onupdate`). Add a regression test, run the suite, then start the app and verify in the browser.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / pytest (backend); Vue 3 + TypeScript (frontend, no changes needed).

---

## Root-Cause Evidence

Database query on `course_assistant.db` confirmed:

```
id=6 | Chap5 Data Link Layer.pdf | status=processing | parse_started_at=None | uploaded_at=2026-07-08 07:26:00
```

Material id=6 has been stuck in "processing" since 2026-07-08 with `parse_started_at = NULL`. The recovery function in `materials.py:72` filters `Material.parse_started_at.isnot(None)`, so this row is invisible to recovery — it will stay "解析中" forever regardless of how many times the user refreshes.

All other materials (id=1–5, 7–10) have `status=ready`. Material id=10 is a re-upload of the same file that parsed successfully.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `backend/app/api/v1/endpoints/materials.py` | Materials list + timeout recovery | Replace `parse_started_at.isnot(None)` + `parse_started_at < threshold` with `func.coalesce(parse_started_at, updated_at) < threshold` so NULL-started materials are recovered using `updated_at` as fallback |
| `backend/app/tests/test_parse_retry_timeout.py` | Existing timeout tests | Add `test_recovers_processing_with_null_parse_started_at` regression test |

---

### Task 1: Fix `_recover_timed_out_materials` to handle NULL `parse_started_at`

**Files:**
- Modify: `backend/app/api/v1/endpoints/materials.py:55-104`

- [ ] **Step 1: Add `func` import and rewrite the recovery query**

Edit `backend/app/api/v1/endpoints/materials.py`. Add `func` to the SQLAlchemy import (line 12 area) and replace the filter in `_recover_timed_out_materials`.

Change the import line:

```python
from sqlalchemy.orm import Session
```

to:

```python
from sqlalchemy import func
from sqlalchemy.orm import Session
```

Then in `_recover_timed_out_materials` (lines 66-76), change:

```python
    threshold = utc_now() - timedelta(seconds=PARSE_TIMEOUT_SECONDS)
    stuck = (
        db.query(Material)
        .filter(
            Material.user_id == user_id,
            Material.status == "processing",
            Material.parse_started_at.isnot(None),
            Material.parse_started_at < threshold,
        )
        .all()
    )
```

to:

```python
    threshold = utc_now() - timedelta(seconds=PARSE_TIMEOUT_SECONDS)
    # Use coalesce(parse_started_at, updated_at) so materials stuck in
    # "processing" with a NULL parse_started_at (legacy rows from before
    # the parse-tracking columns existed, or rows where the endpoint set
    # status="processing" but the background task crashed before setting
    # parse_started_at) are also recovered. updated_at is always set via
    # TimestampMixin.onupdate=func.now(), reflecting the last time the
    # row was modified (i.e. when status was flipped to "processing").
    stuck = (
        db.query(Material)
        .filter(
            Material.user_id == user_id,
            Material.status == "processing",
            func.coalesce(Material.parse_started_at, Material.updated_at)
            < threshold,
        )
        .all()
    )
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd backend; python -c "from app.api.v1.endpoints.materials import _recover_timed_out_materials, PARSE_TIMEOUT_SECONDS; print('OK', PARSE_TIMEOUT_SECONDS)"`
Expected: prints `OK 600`

---

### Task 2: Add regression test for NULL `parse_started_at` recovery (TDD)

**Files:**
- Modify: `backend/app/tests/test_parse_retry_timeout.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/app/tests/test_parse_retry_timeout.py` (after `test_default_parse_timeout_is_600_seconds`):

```python
def test_recovers_processing_with_null_parse_started_at(
    client, tmp_path, monkeypatch
) -> None:
    """A processing material with NULL parse_started_at is recovered.

    Regression: _recover_timed_out_materials used to filter
    ``parse_started_at.isnot(None)``, so a material stuck in "processing"
    with a NULL parse_started_at (legacy row, or endpoint set status but
    background task crashed before setting parse_started_at) was never
    recovered — staying "解析中" forever. The fix uses
    coalesce(parse_started_at, updated_at) so updated_at is the fallback
    timestamp.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.api.v1.endpoints.materials.PARSE_TIMEOUT_SECONDS", 0)

    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, "操作系统")
    material_id = upload_material(
        client, headers, course_id, "notes.txt", b"content"
    )

    db = _test_db(client)
    try:
        # Simulate the stuck state: processing with NULL parse_started_at.
        _force_status(
            db,
            material_id,
            status="processing",
            started_at=None,
            attempts=0,
        )
    finally:
        db.close()

    resp = client.get(
        f"/api/v1/courses/{course_id}/materials", headers=headers
    )
    assert resp.status_code == 200
    item = next(m for m in resp.json()["items"] if m["id"] == material_id)
    assert item["status"] == "failed", (
        f"expected failed, got {item['status']!r} — "
        "NULL parse_started_at materials must be recovered via updated_at"
    )
```

- [ ] **Step 2: Run the test to verify it fails (before the fix is applied)**

Run: `cd backend; python -m pytest app/tests/test_parse_retry_timeout.py::test_recovers_processing_with_null_parse_started_at -v`

Note: if Task 1 was already applied, this test will PASS. If Task 1 has NOT been applied yet, it will FAIL with `assert item["status"] == "failed"` showing `"processing"`.

- [ ] **Step 3: Run the test to verify it passes (after Task 1 fix)**

Run: `cd backend; python -m pytest app/tests/test_parse_retry_timeout.py::test_recovers_processing_with_null_parse_started_at -v`
Expected: PASS

- [ ] **Step 4: Run the full timeout test suite for regressions**

Run: `cd backend; python -m pytest app/tests/test_parse_retry_timeout.py -v`
Expected: all tests pass (including the existing `test_list_materials_recovers_processing_timeout` and the new test)

---

### Task 3: Full regression + commit

**Files:** none (verification + commit only)

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend; python -m pytest -q`
Expected: all pass (340+ tests, including the new NULL-started-at recovery test)

- [ ] **Step 2: Rebuild the frontend (no changes, but confirm no breakage)**

Run: `cd frontend; npm run build`
Expected: build succeeds

- [ ] **Step 3: Commit with the git-commit skill**

Use the `git-commit` skill to stage and commit all changed files with a conventional commit message.

Files to stage:
- `backend/app/api/v1/endpoints/materials.py`
- `backend/app/tests/test_parse_retry_timeout.py`

---

### Task 4: Start the app and verify in browser

**Files:** none (runtime verification)

- [ ] **Step 1: Start the backend + frontend**

Run the start script: `cd f:\course-learning-agent; pwsh -File scripts/start_windows.ps1 -NoOpen`
(Starts backend on :8000, frontend dev server on :5173)

- [ ] **Step 2: Log in and verify the stuck material is recovered**

Using the agent-browser skill:
1. Open `http://localhost:5173`
2. Log in with username `test`, password `test123456`
3. Navigate to the course containing the materials
4. Open the materials page
5. Verify material id=6 "Chap5 Data Link Layer.pdf" is NO LONGER "解析中" — it should now show "解析失败" (failed) with a timeout error message
6. Click "重新处理" to re-parse it and verify it transitions to "已就绪" (ready)

- [ ] **Step 3: Screenshot the final state for confirmation**

---

## Self-Review

**1. Spec coverage:**
- "一直在解析中" (stuck in parsing) → Task 1 (coalesce fix) makes the recovery logic handle NULL parse_started_at; Task 2 locks it in with a test. ✓
- "解决后自己启动检查" → Task 4 starts the app and verifies in the browser. ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling" present. Every code step shows the actual code. ✓

**3. Type consistency:** `func.coalesce(Material.parse_started_at, Material.updated_at)` uses columns that both exist on the Material model (parse_started_at from the model definition, updated_at from TimestampMixin). The test helper `_force_status` with `started_at=None` matches the NULL scenario. `PARSE_TIMEOUT_SECONDS` is monkeypatched to 0 in the test, same pattern as the existing `test_list_materials_recovers_processing_timeout`. ✓
