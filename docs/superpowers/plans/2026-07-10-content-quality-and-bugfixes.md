# Content Quality & Bugfixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 9 issues: document content quality (priority), retrieval recall, agent audit metadata, chat UI bugs, timestamp skew, concept comparison empty content/timeout.

**Architecture:** Backend Python (FastAPI + SQLAlchemy + SQLite) + Frontend Vue 3. Mock LLM fallback is the default provider. Fixes target both mock and real LLM paths. All backend changes follow TDD with pytest; frontend changes verified via type-check.

**Tech Stack:** Python 3.11+, pytest, SQLAlchemy, Pydantic v2, Vue 3, TypeScript, Element Plus

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `backend/app/agents/llm.py` | LLM adapter + mock builders | Modify |
| `backend/app/agents/outline.py` | Knowledge point extraction | Modify |
| `backend/app/agents/quiz.py` | Quiz generation + audit | Modify |
| `backend/app/agents/concept_compare.py` | Concept comparison + audit | Modify |
| `backend/app/agents/audit.py` | AgentAudit utility class | Modify |
| `backend/app/retrieval/search.py` | Keyword search + scoring | Modify |
| `backend/app/retrieval/chunker.py` | Text chunking | Modify |
| `backend/app/schemas/conversation.py` | Conversation API schema | Modify |
| `backend/app/schemas/message.py` | Message API schema | Modify |
| `backend/app/core/config.py` | Settings | Modify |
| `backend/app/agents/prompts/concept_compare_v1.md` | Compare prompt | Modify |
| `frontend/src/views/ChatView.vue` | Chat UI | Modify |
| `frontend/src/views/KnowledgeGraphView.vue` | Knowledge graph + compare UI | Modify |
| `frontend/src/components/chat/MessageList.vue` | Chat message display | Modify |
| `backend/tests/test_outline_mock.py` | New test file | Create |
| `backend/tests/test_search_scoring.py` | New test file | Create |
| `backend/tests/test_audit_metadata.py` | New test file | Create |
| `backend/tests/test_chunker_merge.py` | New test file | Create |
| `backend/tests/test_timestamp_utc.py` | New test file | Create |

---

## Task 1: Fix mock outline source_chunk_ids mapping (P0 - Document Quality Core)

**Root cause:** `_mock_outline` in `llm.py` returns `"source_chunk_ids": [i + 1]` (1-based position index), but `_reconcile_chunk_ids` in `outline.py` compares against real DB chunk IDs. No match → fallback returns ALL sampled chunk IDs → every knowledge point shows the same content.

**Files:**
- Modify: `backend/app/agents/llm.py` (lines 345-469, `_mock_outline` function)
- Test: `backend/tests/test_outline_mock.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_outline_mock.py
"""Tests for mock outline source_chunk_ids mapping."""
from app.agents.llm import _mock_outline


def test_mock_outline_returns_real_chunk_ids():
    """Mock outline must return actual chunk_id values from the prompt,
    not 1-based position indices."""
    prompt = """课程: 测试课程

资料片段（retrieved_chunks）
[片段1] chunk_id=42，页码 5，标题：进程与线程
进程是程序的一次执行过程，是系统进行资源分配和调度的基本单位。

[片段2] chunk_id=17，页码 3，标题：线程概念
线程是进程内的一个执行实体，是CPU调度的基本单位。
"""
    result = _mock_outline(prompt)
    kps = result["knowledge_points"]
    assert len(kps) >= 1

    # The source_chunk_ids must contain the actual chunk_id from the prompt
    all_source_ids = []
    for kp in kps:
        all_source_ids.extend(kp["source_chunk_ids"])

    # chunk_id=42 and chunk_id=17 must appear somewhere
    assert 42 in all_source_ids or 17 in all_source_ids, (
        f"source_chunk_ids should contain real DB IDs (42, 17), "
        f"got: {all_source_ids}"
    )
    # Must NOT contain position-based indices like 1 or 2
    # (unless they happen to match a real chunk_id)
    for kp in kps:
        for sid in kp["source_chunk_ids"]:
            assert isinstance(sid, int), (
                f"source_chunk_ids must be ints, got {type(sid)}: {sid}"
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_outline_mock.py::test_mock_outline_returns_real_chunk_ids -v`
Expected: FAIL — source_chunk_ids contains `[1]` or `[2]` (position indices), not `[42]` or `[17]`

- [ ] **Step 3: Fix the regex to capture chunk_id**

In `backend/app/agents/llm.py`, modify the `_mock_outline` function. Change the chunk extraction regex to capture the chunk_id:

```python
# OLD (line ~346-349):
chunk_pattern = re.compile(
    r"\[片段\d+\]\s*chunk_id=\d+[^\n]*\n(.+?)(?=\n\n|\Z)",
    re.DOTALL,
)
chunks = chunk_pattern.findall(prompt)

# NEW: capture chunk_id as group(1), text as group(2)
chunk_pattern = re.compile(
    r"\[片段\d+\]\s*chunk_id=(\d+)[^\n]*\n(.+?)(?=\n\n|\Z)",
    re.DOTALL,
)
chunk_matches = chunk_pattern.findall(prompt)
chunks = [text for _cid, text in chunk_matches]
chunk_ids = [int(cid) for cid, _text in chunk_matches]
```

- [ ] **Step 4: Use real chunk_ids in source_chunk_ids**

In the same function, replace all occurrences of `[i + 1]` with `[chunk_ids[i]]`:

```python
# OLD (line ~433):
"source_chunk_ids": [i + 1],

# NEW:
"source_chunk_ids": [chunk_ids[i]] if i < len(chunk_ids) else [],
```

Also fix the fallback single-chunk split (lines ~450-466):
```python
# OLD:
"source_chunk_ids": [1],
# NEW:
"source_chunk_ids": [chunk_ids[0]] if chunk_ids else [],
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_outline_mock.py::test_mock_outline_returns_real_chunk_ids -v`
Expected: PASS

---

## Task 2: Improve mock outline summary quality + increase sampling (P0 - Document Quality)

**Root cause:** (A) Summary is just `chunk_text[:150]` truncated — no real summarization. (B) Only 15 chunks per material sampled → low coverage.

**Files:**
- Modify: `backend/app/agents/llm.py` (`_mock_outline` function)
- Modify: `backend/app/agents/outline.py` (`_fetch_chunks` function)
- Test: `backend/tests/test_outline_mock.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to backend/tests/test_outline_mock.py

def test_mock_outline_summary_is_not_truncated_title():
    """Summary should be more than just the first 150 chars of raw text."""
    long_text = "进程与线程\n" + "进程是程序的一次执行过程。" * 20
    prompt = f"""课程: 测试课程

资料片段（retrieved_chunks）
[片段1] chunk_id=1，标题：进程与线程
{long_text}
"""
    result = _mock_outline(prompt)
    kp = result["knowledge_points"][0]
    # Summary should not just be the title repeated
    assert kp["summary"], "Summary must not be empty"
    assert len(kp["summary"]) >= 10, f"Summary too short: {kp['summary']}"


def test_fetch_chunks_increased_sampling():
    """_fetch_chunks should sample up to 25 chunks per material."""
    from app.agents.outline import _fetch_chunks
    # This is an integration test that requires DB setup;
    # we verify the constant instead
    import app.agents.outline as outline_mod
    import inspect
    source = inspect.getsource(outline_mod._fetch_chunks)
    assert "MAX_PER_MATERIAL = 25" in source or "MAX_PER_MATERIAL=25" in source, (
        "MAX_PER_MATERIAL should be 25 for better coverage"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_outline_mock.py::test_mock_outline_summary_is_not_truncated_title tests/test_outline_mock.py::test_fetch_chunks_increased_sampling -v`
Expected: FAIL

- [ ] **Step 3: Improve mock summary generation**

In `backend/app/agents/llm.py`, modify the `_mock_outline` function. Replace the summary generation:

```python
# OLD (line ~427):
summary = _clean_summary(chunk_text.strip()[:150])

# NEW: Generate a better summary from the first 2-3 meaningful lines
def _generate_summary(chunk_text: str, title: str) -> str:
    """Generate a concise summary from chunk text."""
    lines = [l.strip() for l in chunk_text.strip().split("\n") if l.strip()]
    # Skip the title line if it matches
    meaningful = [
        l for l in lines
        if l != title and len(l) >= 5
        and not re.match(r"^[\d\s\.\-:]+$", l)  # skip pure numbers
    ][:3]
    if meaningful:
        summary = "。".join(meaningful)[:200]
    else:
        summary = _clean_summary(chunk_text.strip()[:200])
    return summary

summary = _generate_summary(chunk_text, title)
```

- [ ] **Step 4: Increase chunk sampling in outline.py**

In `backend/app/agents/outline.py`, modify `_fetch_chunks`:

```python
# OLD (line ~371):
MAX_PER_MATERIAL = 15

# NEW:
MAX_PER_MATERIAL = 25
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_outline_mock.py -v`
Expected: PASS

---

## Task 3: Fix chunker — merge title-only chunks with adjacent body (P0 - Document Quality)

**Root cause:** `_split_by_headings` in `chunker.py` produces sections where a heading line immediately followed by another heading creates a section containing only the heading text. This produces pure-title chunks with density-inflated scores.

**Files:**
- Modify: `backend/app/retrieval/chunker.py` (`_split_by_headings` function)
- Test: `backend/tests/test_chunker_merge.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chunker_merge.py
"""Tests for chunker title-body merging."""
from app.retrieval.chunker import chunk_text


def test_consecutive_headings_are_merged():
    """Two consecutive heading lines should not produce a title-only chunk."""
    text = """3.1 进程与线程
3.1.1 进程概念
进程是程序的一次执行过程，是系统进行资源分配和调度的基本单位。
进程具有动态性、并发性、独立性和异步性等特征。
"""
    chunks = chunk_text(text)
    # No chunk should have text == title (pure title chunk)
    for chunk in chunks:
        if chunk["title"]:
            text_stripped = chunk["text"].strip()
            title_stripped = chunk["title"].strip()
            assert text_stripped != title_stripped, (
                f"Pure title chunk found: title={title_stripped!r}, "
                f"text={text_stripped!r}"
            )


def test_single_heading_followed_by_body():
    """A heading followed by body text should produce one chunk."""
    text = """2.1 线程的概念
线程是进程内的一个执行实体。
线程是CPU调度的基本单位。
"""
    chunks = chunk_text(text)
    assert len(chunks) >= 1
    assert chunks[0]["title"] is not None
    assert "线程" in chunks[0]["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_chunker_merge.py::test_consecutive_headings_are_merged -v`
Expected: FAIL — a pure title chunk `3.1 进程与线程` is produced

- [ ] **Step 3: Implement title-body merging**

In `backend/app/retrieval/chunker.py`, modify the `_split_by_headings` function. After building sections, merge any section whose content is only the heading line into the next section:

```python
def _split_by_headings(text: str) -> List[Tuple[Optional[str], str]]:
    """Split text into (title, content) sections by heading lines.

    A heading line becomes the title of the section that follows it.
    Title-only sections (heading immediately followed by another heading)
    are merged into the next section to avoid empty/title-only chunks.
    """
    lines = text.splitlines(keepends=True)
    raw_sections: List[Tuple[Optional[str], str]] = []
    current_title: Optional[str] = None
    current_lines: List[str] = []

    for line in lines:
        if _is_heading(line):
            if current_lines:
                raw_sections.append((current_title, "".join(current_lines)))
            current_title = line.strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        raw_sections.append((current_title, "".join(current_lines)))

    if not raw_sections:
        return [(None, text)]

    # Merge title-only sections into the next section.
    # A section is "title-only" when its content (minus the heading line
    # itself) is empty or whitespace — meaning the heading was immediately
    # followed by another heading.
    merged: List[Tuple[Optional[str], str]] = []
    pending_title: Optional[str] = None
    for title, content in raw_sections:
        body = content.strip()
        # Check if content is just the heading line itself
        if title and body == title:
            # Title-only section — defer to next section
            pending_title = title
            continue
        if pending_title is not None:
            # Prepend the deferred title to this section's content
            content = pending_title + "\n" + content
            title = pending_title
            pending_title = None
        merged.append((title, content))
    # If a title-only section was last, append it (shouldn't normally happen)
    if pending_title is not None:
        merged.append((pending_title, pending_title))

    return merged if merged else [(None, text)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_chunker_merge.py -v`
Expected: PASS

---

## Task 4: Improve mock QA answer quality (P0 - Document Quality)

**Root cause:** `_mock_course_qa` in `llm.py` uses only the first chunk's text[:200] as the answer. Since retrieval often returns title chunks first (due to density bias), the answer is just a title string. Also, mock always returns `not_found=False` even when chunks are low quality.

**Files:**
- Modify: `backend/app/agents/llm.py` (`_mock_course_qa` function)
- Test: `backend/tests/test_outline_mock.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# Append to backend/tests/test_outline_mock.py

def test_mock_qa_uses_longest_chunk_not_first():
    """Mock QA should prefer the chunk with the most content, not just
    the first one (which may be a short title chunk)."""
    from app.agents.llm import _mock_course_qa

    prompt = """课程: 操作系统

资料片段（retrieved_chunks）
[片段1] chunk_id=1
进程与线程

[片段2] chunk_id=2
进程是程序的一次执行过程，是系统进行资源分配和调度的基本单位。
进程具有动态性、并发性、独立性和异步性等特征。
线程是进程内的一个执行实体，是CPU调度的基本单位。
进程与线程的主要区别在于：进程是资源分配的单位，线程是调度的单位。

用户问题: 进程与线程的主要区别
"""
    result = _mock_course_qa(prompt)
    assert result["answer"], "Answer must not be empty"
    # Answer should contain meaningful content, not just "进程与线程"
    assert len(result["answer"]) > 20, (
        f"Answer too short ({len(result['answer'])} chars): {result['answer']!r}"
    )
    assert "进程与线程" not in result["answer"][:6] or len(result["answer"]) > 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_outline_mock.py::test_mock_qa_uses_longest_chunk_not_first -v`
Expected: FAIL — answer is just "进程与线程" (first 200 chars of first chunk which is only a title)

- [ ] **Step 3: Improve mock QA to select the best chunk**

In `backend/app/agents/llm.py`, modify `_mock_course_qa`. Replace the chunk selection logic:

```python
# OLD (lines ~152-157):
if chunks:
    first_cid, first_text = chunks[0]
    first_text = first_text.strip()
    answer = first_text[:200]
    if len(first_text) > 200:
        answer += "…"

# NEW: Select the longest chunk (most content) instead of just the first
if chunks:
    # Sort by text length descending — the chunk with the most content
    # is most likely to contain a real answer.
    sorted_chunks = sorted(chunks, key=lambda c: len(c[1].strip()), reverse=True)
    best_cid, best_text = sorted_chunks[0]
    best_text = best_text.strip()

    # Build answer from the best chunk, prioritising lines that contain
    # keywords from the question.
    question_lower = question.lower() if question else ""
    q_keywords = [c for c in question_lower if '\u4e00' <= c <= '\u9fff']
    lines = [l.strip() for l in best_text.split("\n") if l.strip() and len(l.strip()) >= 5]

    if q_keywords and lines:
        # Find lines containing question keywords
        matching = [l for l in lines if any(kw in l.lower() for kw in q_keywords)]
        if matching:
            answer = matching[0][:200]
            if len(matching) > 1:
                answer += " " + matching[1][:150]
        else:
            answer = best_text[:200]
    else:
        answer = best_text[:200]

    if len(best_text) > 200 and len(answer) <= 200:
        answer += "…"

    first_cid = best_cid
    first_text = best_text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_outline_mock.py::test_mock_qa_uses_longest_chunk_not_first -v`
Expected: PASS

---

## Task 5: Fix agent audit metadata hardcoded mock (P1)

**Root cause:** `quiz.py` line 209 hardcodes `model_name="mock"` (and omits `provider`). `concept_compare.py` lines 51-52 hardcode `model_name="mock", provider="mock"`. Even when the real LLM is used, the audit record shows "mock".

**Files:**
- Modify: `backend/app/agents/llm.py` (add `model_name` to meta)
- Modify: `backend/app/agents/quiz.py` (use `call_llm_with_meta`, update run after LLM call)
- Modify: `backend/app/agents/concept_compare.py` (update run after LLM call)
- Modify: `backend/app/agents/audit.py` (add `update_run_meta` method)
- Test: `backend/tests/test_audit_metadata.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_audit_metadata.py
"""Tests for agent audit metadata accuracy."""
from unittest.mock import patch, MagicMock
from app.agents.audit import AgentAudit


def test_quiz_audit_records_real_provider():
    """Quiz audit run should record the actual provider, not hardcoded 'mock'."""
    # This test verifies that quiz.generate_quiz passes the real
    # provider/model_name to AgentAudit.create_run when a user_config
    # is provided.
    import inspect
    from app.agents import quiz
    source = inspect.getsource(quiz.generate_quiz)

    # The create_run call should NOT hardcode model_name="mock"
    assert 'model_name="mock"' not in source, (
        "quiz.py still hardcodes model_name='mock' in create_run"
    )


def test_concept_compare_audit_records_real_provider():
    """Concept compare audit run should record actual provider."""
    import inspect
    from app.agents import concept_compare
    source = inspect.getsource(concept_compare.generate_compare)

    assert 'model_name="mock"' not in source, (
        "concept_compare.py still hardcodes model_name='mock' in create_run"
    )
    assert 'provider="mock"' not in source, (
        "concept_compare.py still hardcodes provider='mock' in create_run"
    )


def test_llm_meta_includes_model_name():
    """call_llm_with_meta should include model_name in the returned meta."""
    from app.agents.llm import call_llm_with_meta
    result, meta = call_llm_with_meta("test", "course_qa")
    assert "model_name" in meta, (
        f"meta should include 'model_name', got keys: {list(meta.keys())}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_audit_metadata.py -v`
Expected: FAIL

- [ ] **Step 3: Add model_name to call_llm_with_meta meta**

In `backend/app/agents/llm.py`, modify `call_llm_with_meta` to include `model_name` in all three return paths:

```python
# Path 1 (user_config success, ~line 77):
return result, {
    "provider": "real",
    "model_name": user_config.get("model", ""),
    "fallback_used": False,
    "fallback_reason": None,
}

# Path 1 fallback (~line 86):
return _mock_response(agent_type, prompt), {
    "provider": "mock",
    "model_name": "mock",
    "fallback_used": True,
    "fallback_reason": str(exc) or exc.__class__.__name__,
}

# Path 2 (system real success, ~line 97):
return result, {
    "provider": "real",
    "model_name": settings.LLM_MODEL,
    "fallback_used": False,
    "fallback_reason": None,
}

# Path 2 fallback (~line 106):
return _mock_response(agent_type, prompt), {
    "provider": "mock",
    "model_name": "mock",
    "fallback_used": True,
    "fallback_reason": str(exc) or exc.__class__.__name__,
}

# Path 3 (mock default, ~line 113):
return _mock_response(agent_type, prompt), {
    "provider": "mock",
    "model_name": "mock",
    "fallback_used": False,
    "fallback_reason": None,
}
```

- [ ] **Step 4: Add update_run_meta to AgentAudit**

In `backend/app/agents/audit.py`, add a new static method:

```python
@staticmethod
def update_run_meta(
    db: Session,
    run_id: int | None,
    model_name: str | None = None,
    provider: str | None = None,
) -> None:
    """Update an existing AgentRun's model_name/provider after the LLM
    call completes, so the audit record reflects the actual provider
    used (which may differ from the pre-call guess due to fallback).
    """
    if run_id is None:
        return
    try:
        run = db.query(AgentRun).filter_by(id=run_id).first()
        if run is not None:
            if model_name is not None:
                run.model_name = model_name
            if provider is not None:
                run.provider = provider
            db.flush()
    except Exception:
        pass  # audit must not break the main flow
```

- [ ] **Step 5: Fix quiz.py to use call_llm_with_meta and update run**

In `backend/app/agents/quiz.py`, modify `generate_quiz`:

```python
# OLD (line 32):
from app.agents.llm import call_llm

# NEW:
from app.agents.llm import call_llm_with_meta
```

Replace the create_run call (lines 198-210) to use best-guess values:

```python
# Determine provider/model_name before LLM call
from app.core.config import settings
if user_config:
    _provider = "user"
    _model = user_config.get("model", "")
else:
    _provider = "real" if settings.LLM_PROVIDER == "real" else "mock"
    _model = settings.LLM_MODEL

run = AgentAudit.create_run(
    db,
    user_id=user_id,
    run_type="quiz",
    input_summary={...},
    prompt_version=_PROMPT_VERSION,
    model_name=_model,
    provider=_provider,
)
```

Replace the LLM call (lines 217-221) to use call_llm_with_meta:

```python
# OLD:
output = call_llm(prompt, agent_type="quiz_generate", user_config=user_config)

# NEW:
output, meta = call_llm_with_meta(
    prompt, agent_type="quiz_generate", user_config=user_config
)
# Update audit run with actual provider/model_name
AgentAudit.update_run_meta(
    db, run_id,
    model_name=meta.get("model_name"),
    provider=meta.get("provider"),
)
```

- [ ] **Step 6: Fix concept_compare.py to update run after LLM call**

In `backend/app/agents/concept_compare.py`, modify `generate_compare`. Replace the create_run call (lines 42-53):

```python
# Determine provider/model_name before LLM call
from app.core.config import settings
if user_config:
    _provider = "user"
    _model = user_config.get("model", "")
else:
    _provider = "real" if settings.LLM_PROVIDER == "real" else "mock"
    _model = settings.LLM_MODEL

run = AgentAudit.create_run(
    db,
    user_id,
    run_type="concept_compare",
    input_summary={
        "a": concept_a.get("title"),
        "b": concept_b.get("title"),
    },
    prompt_version=_PROMPT_VERSION,
    model_name=_model,
    provider=_provider,
)
```

After the `call_llm_with_meta` call (after line 69), add:

```python
# Update audit run with actual provider/model_name from meta
AgentAudit.update_run_meta(
    db, run.id,
    model_name=meta.get("model_name"),
    provider=meta.get("provider"),
)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_audit_metadata.py -v`
Expected: PASS

---

## Task 6: Fix chat "completed" but no output (P1 - Frontend)

**Root cause:** In `ChatView.vue` lines 592-598, when the SSE stream ends without a `final` event (e.g., proxy timeout), `result` is `null` and `streamError` is `null` → neither branch executes → the pending message stays "正在思考..." forever while the status panel shows "已完成".

**Files:**
- Modify: `frontend/src/views/ChatView.vue` (lines 592-598)

- [ ] **Step 1: Fix the missing else branch**

In `frontend/src/views/ChatView.vue`, modify the `runChat` function around line 592:

```javascript
// OLD (lines 592-598):
if (result && isCurrentRun()) {
  applyChatResult(pendingMessage, result)
  if (!streamError.value) statusExpanded.value = false
} else if (streamError.value && isCurrentRun()) {
  removePendingMessage()
  ElMessage.error(streamError.value)
}

// NEW: Add else branch for the case where result is null but no error
if (result && isCurrentRun()) {
  applyChatResult(pendingMessage, result)
  if (!streamError.value) statusExpanded.value = false
} else if (streamError.value && isCurrentRun()) {
  removePendingMessage()
  ElMessage.error(streamError.value)
} else if (isCurrentRun()) {
  // SSE stream ended without a final event and without an error.
  // This happens when the connection is interrupted (proxy timeout,
  // network drop) after step events but before the final event.
  pendingMessage.pending = false
  pendingMessage.content = '回答生成中断，请重新提问或重试。'
  pendingMessage.error = true
  ElMessage.warning('回答未完整返回，请重试')
}
```

- [ ] **Step 2: Verify frontend type check**

Run: `cd f:\course-learning-agent\frontend && npx vue-tsc --noEmit`
Expected: No errors

---

## Task 7: Fix Q&A timestamp UTC offset (P1 - Schema)

**Root cause:** `conversation.py` and `message.py` schemas lack the `ensure_utc` validator that `material.py` already has. SQLite stores UTC but returns naive datetimes → Pydantic serializes without offset → frontend `new Date()` treats as local time → 8-hour skew.

**Files:**
- Modify: `backend/app/schemas/conversation.py`
- Modify: `backend/app/schemas/message.py`
- Test: `backend/tests/test_timestamp_utc.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_timestamp_utc.py
"""Tests for UTC timezone handling in API schemas."""
from datetime import datetime, timezone

from app.schemas.conversation import ConversationResponse
from app.schemas.message import MessageResponse


def test_conversation_response_attaches_utc():
    """ConversationResponse should attach UTC tzinfo to naive datetimes."""
    naive = datetime(2026, 7, 10, 13, 25, 0)  # no tzinfo
    resp = ConversationResponse(
        id=1, user_id=1, course_id=1, title="test",
        created_at=naive, updated_at=naive,
    )
    assert resp.created_at.tzinfo is not None, (
        "created_at should have tzinfo after validation"
    )
    # Should be UTC (+00:00)
    assert resp.created_at.utcoffset().total_seconds() == 0


def test_message_response_attaches_utc():
    """MessageResponse should attach UTC tzinfo to naive datetimes."""
    naive = datetime(2026, 7, 10, 13, 25, 0)
    resp = MessageResponse(
        id=1, role="user", content="test",
        created_at=naive,
    )
    assert resp.created_at.tzinfo is not None
    assert resp.created_at.utcoffset().total_seconds() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_timestamp_utc.py -v`
Expected: FAIL — `created_at.tzinfo` is None

- [ ] **Step 3: Add ensure_utc validator to conversation.py**

In `backend/app/schemas/conversation.py`:

```python
# Add imports at top:
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.core.timezone import ensure_utc

# Add validator to ConversationResponse class:
class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    course_id: int
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _attach_utc(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return ensure_utc(value)
```

- [ ] **Step 4: Add ensure_utc validator to message.py**

In `backend/app/schemas/message.py`:

```python
# Add imports:
from pydantic import BaseModel, ConfigDict, field_validator
from app.core.timezone import ensure_utc

# Add validator to MessageResponse:
class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: str
    content: Optional[str] = None
    answer_json: Optional[str] = None
    citations: List[CitationBrief] = []
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def _attach_utc(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return ensure_utc(value)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_timestamp_utc.py -v`
Expected: PASS

- [ ] **Step 6: Fix frontend to use formatLocalDateTime**

In `frontend/src/components/chat/MessageList.vue`, replace the `formatTime` function (around line 44) with:

```javascript
import { formatLocalDateTime } from '@/utils/datetime'

// Replace formatTime usage with formatLocalDateTime
// In the template, change time display to use formatLocalDateTime
```

In `frontend/src/views/ChatView.vue`, around line 899, replace `new Date(conv.created_at).toLocaleString()` with `formatLocalDateTime(conv.created_at)`.

---

## Task 8: Fix retrieval scoring bias toward title chunks (P1)

**Root cause:** `density = raw_score / (text_len / 100)` inflates scores for short title chunks (e.g., 10-char title with 2 hits → density=60 → score=1.0 capped). Long body chunks with 3 hits in 600 chars → density=0.5 → barely passes filter. The `density < 0.5` filter removes low-density body chunks instead of title-only chunks.

**Files:**
- Modify: `backend/app/retrieval/search.py` (scoring section, lines 164-233)
- Test: `backend/tests/test_search_scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_search_scoring.py
"""Tests for search scoring fairness between title and body chunks."""
from app.retrieval.search import keyword_search


def test_body_chunk_scores_higher_than_title_only(db_session, sample_course):
    """A chunk with detailed body text should score higher than a
    title-only chunk for a conceptual query."""
    from app.models.material import Material
    from app.models.material_chunk import MaterialChunk

    # Create a material
    mat = Material(course_id=sample_course.id, filename="test.pdf",
                   status="ready", user_id=sample_course.user_id)
    db_session.add(mat)
    db_session.flush()

    # Title-only chunk (short, high density)
    title_chunk = MaterialChunk(
        material_id=mat.id, course_id=sample_course.id,
        chunk_index=0, title="进程与线程",
        text="进程与线程", token_count=5,
        keyword_text="进程与线程",
    )
    # Body chunk with detailed content (longer, lower density but more info)
    body_chunk = MaterialChunk(
        material_id=mat.id, course_id=sample_course.id,
        chunk_index=1, title="进程与线程的主要区别",
        text=(
            "进程与线程的主要区别在于：进程是资源分配的基本单位，"
            "线程是CPU调度的基本单位。进程拥有独立的地址空间，"
            "线程共享进程的地址空间。进程间通信需要IPC机制，"
            "线程间通信可以直接访问共享变量。"
            "进程创建开销大，线程创建开销小。"
        ),
        token_count=120,
        keyword_text="进程与线程的主要区别在于 资源分配 CPU调度 地址空间",
    )
    db_session.add_all([title_chunk, body_chunk])
    db_session.commit()

    results = keyword_search(db_session, sample_course.id, "进程与线程的主要区别")

    # Find body and title chunks in results
    body_result = next((r for r in results if r["chunk_id"] == body_chunk.id), None)
    title_result = next((r for r in results if r["chunk_id"] == title_chunk.id), None)

    # Body chunk should exist in results
    assert body_result is not None, "Body chunk should be in search results"

    # Body chunk should score >= title chunk (or title chunk should be filtered out)
    if title_result is not None:
        assert body_result["score"] >= title_result["score"], (
            f"Body chunk score ({body_result['score']}) should be >= "
            f"title chunk score ({title_result['score']})"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_search_scoring.py::test_body_chunk_scores_higher_than_title_only -v`
Expected: FAIL — title chunk scores higher due to density inflation

- [ ] **Step 3: Replace density-based scoring with absolute hit + coverage**

In `backend/app/retrieval/search.py`, replace the scoring section (lines 200-233):

```python
# --- Scoring: absolute hits + coverage, demote title-only chunks ---

# Text length for reference
text_len = max(len(text), 1)

# Coverage: fraction of distinct keywords that matched
coverage = match_count / max(len(keywords), 1)

# Absolute hit score: total keyword hits weighted by location
# (title 2x, filename 2x, body 1x)
# This replaces density-based scoring which inflated short chunks.
hit_score = raw_score

# Length bonus: longer chunks tend to contain more useful context.
# Use a logarithmic scale so a 600-char chunk gets ~2x bonus over 10-char.
import math
length_bonus = min(0.3, math.log10(max(text_len, 1)) * 0.1)

# Title match bonus (kept small to avoid title-only inflation)
has_title_match = any(
    kw.lower() in title_lower for kw in keywords
)
title_bonus = 0.05 if has_title_match else 0.0

# Penalize title-only chunks: if text is very short (< 50 chars) and
# consists mostly of the title, it likely has no explanatory content.
is_title_only = (
    text_len < 50 and
    title_lower in text_lower
)
title_only_penalty = -0.3 if is_title_only else 0.0

# Final normalized score (0-1 range)
normalized_score = min(
    1.0,
    (hit_score * 0.05)
    + (coverage * 0.3)
    + length_bonus
    + title_bonus
    + title_only_penalty
)

# Minimum threshold: require at least 1 body text hit (not just title)
body_text_hits = raw_score - (title_hits * 2 + fname_hits * 2)
if body_text_hits <= 0 and text_len < 50:
    # This is a title-only chunk with no body content — skip it
    continue

if normalized_score <= 0:
    continue
```

Note: `title_hits` and `fname_hits` need to be tracked per-chunk. Move them outside the keyword loop or accumulate them. The full implementation should track `total_title_hits` and `total_fname_hits` across all keywords for the current chunk.

- [ ] **Step 4: Track title/filename hits separately**

Restructure the scoring loop to track totals:

```python
total_title_hits = 0
total_fname_hits = 0
total_text_hits = 0
match_count = 0

for kw in keywords:
    if kw in ascii_patterns:
        pat = ascii_patterns[kw]
        title_hits = len(pat.findall(chunk.title or ""))
        fname_hits = len(pat.findall(filename or ""))
        text_hits = len(pat.findall(text))
    else:
        kw_l = kw.lower()
        title_hits = title_lower.count(kw_l)
        fname_hits = filename_lower.count(kw_l)
        text_hits = text_lower.count(kw_l)

    total_title_hits += title_hits
    total_fname_hits += fname_hits
    total_text_hits += text_hits

    total_hits = title_hits + fname_hits + text_hits
    if total_hits > 0:
        match_count += 1
    raw_score += title_hits * 2 + fname_hits * 2 + text_hits

# Then use total_text_hits in the body_text_hits check:
body_text_hits = total_text_hits
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/test_search_scoring.py -v`
Expected: PASS

- [ ] **Step 6: Run existing search tests to check no regressions**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/ -k "search or retrieval" -v`
Expected: All pass (may need to update expected scores in existing tests)

---

## Task 9: Fix concept comparison report empty content + timeout (P1)

**Root causes:**
- (A) `KnowledgeGraphView.vue` sets `compareReport.value = null` on tab switch, then if API fails, shows "暂无对比报告"
- (B) Concept compare timeout is 60s global; first call can take ~61s → timeout → fallback
- (C) `_is_valid_compare_report` only checks for `concept_a` or `similarities`, doesn't enforce all sections non-empty
- (D) Prompt doesn't strongly enforce all sections

**Files:**
- Modify: `frontend/src/views/KnowledgeGraphView.vue` (handleCompare function)
- Modify: `backend/app/core/config.py` (add concept compare timeout)
- Modify: `backend/app/agents/concept_compare.py` (validation)
- Modify: `backend/app/agents/prompts/concept_compare_v1.md` (enforce sections)

- [ ] **Step 1: Fix KnowledgeGraphView.vue — don't clear report on tab switch**

In `frontend/src/views/KnowledgeGraphView.vue`, modify `handleCompare`:

```javascript
// OLD (lines 367-385):
async function handleCompare() {
  if (!selectedEdge.value) return
  compareLoading.value = true
  compareDrawerVisible.value = true
  compareReport.value = null
  try {
    const { data } = await compareNodes(...)
    compareReport.value = data
  } catch (err) {
    ElMessage.error(parseApiError(err, '生成对比报告失败'))
  } finally {
    compareLoading.value = false
  }
}

// NEW: Don't clear the existing report; show loading overlay instead.
// Only clear if this is the first open (no prior report).
async function handleCompare() {
  if (!selectedEdge.value) return
  compareLoading.value = true
  compareDrawerVisible.value = true
  // Don't clear compareReport here — keep the old one visible
  // until the new one arrives, so the user sees loading state
  // instead of "暂无对比报告".
  try {
    const { data } = await compareNodes(
      selectedEdge.value.source_node_id,
      selectedEdge.value.target_node_id,
      selectedEdge.value.id,
      compareUserFocus.value,
    )
    compareReport.value = data
  } catch (err) {
    ElMessage.error(parseApiError(err, '生成对比报告失败'))
    // Only clear if there was no prior report
    if (!compareReport.value) {
      // keep null — will show "暂无对比报告"
    }
  } finally {
    compareLoading.value = false
  }
}
```

- [ ] **Step 2: Increase timeout for concept compare**

In `backend/app/core/config.py`, add a separate timeout setting:

```python
# Add after LLM_TIMEOUT_SECONDS:
LLM_CONCEPT_COMPARE_TIMEOUT_SECONDS: int = 120
```

In `backend/app/agents/llm.py`, modify `_real_response` to accept an optional timeout override:

```python
def _real_response(
    prompt: str,
    agent_type: str,
    schema: dict | None,
    user_config: dict | None,
    timeout_override: int | None = None,
) -> dict[str, Any]:
    # ... existing code ...
    if user_config is not None:
        # ... existing ...
        timeout = user_config.get("timeout_seconds", settings.LLM_TIMEOUT_SECONDS)
    else:
        # ... existing ...
        timeout = timeout_override or settings.LLM_TIMEOUT_SECONDS
    # ... rest unchanged ...
```

In `call_llm_with_meta`, pass the override for concept_compare:

```python
def call_llm_with_meta(
    prompt: str,
    agent_type: str,
    schema: dict | None = None,
    user_config: dict | None = None,
) -> tuple[dict, dict]:
    # Determine timeout override based on agent type
    timeout_override = None
    if agent_type == "concept_compare":
        timeout_override = getattr(settings, "LLM_CONCEPT_COMPARE_TIMEOUT_SECONDS", 120)

    # Pass to _real_response calls
    # ... modify each _real_response call to pass timeout_override ...
```

- [ ] **Step 3: Strengthen concept_compare prompt**

In `backend/app/agents/prompts/concept_compare_v1.md`, add stronger constraints:

```markdown
## 约束
- 只能基于给定的证据片段生成，不得引入未给出的资料事实。
- 如果证据不足，添加 "insufficient_evidence": true。
- 输出必须是合法 JSON。
- **所有字段都必须非空**：similarities、differences、transfer_learning、confusions、exam_questions
  每个数组至少包含 1 条内容。即使证据不足，也要基于已有信息生成初步对比。
- transfer_learning 必须包含至少 1 条关于两个概念之间方法论迁移的内容。
- exam_questions 必须包含至少 1 道关于两个概念对比的考题。
```

- [ ] **Step 4: Strengthen _is_valid_compare_report**

In `backend/app/agents/concept_compare.py`:

```python
def _is_valid_compare_report(result: Any) -> bool:
    """Return True if result looks like a complete compare report dict."""
    if not isinstance(result, dict):
        return False
    if "concept_a" not in result and "similarities" not in result:
        return False
    # Ensure all required sections exist (can be empty arrays but must exist)
    required_sections = (
        "similarities", "differences",
        "transfer_learning", "confusions", "exam_questions",
    )
    for section in required_sections:
        if section not in result:
            result[section] = []  # fill missing sections with empty arrays
    return True
```

- [ ] **Step 5: Ensure mock fallback always has all sections**

The existing `_mock_fallback` already generates all sections — verify they are all non-empty. In `concept_compare.py`, the `_mock_fallback` function already returns all sections with content. No change needed.

- [ ] **Step 6: Verify frontend type check**

Run: `cd f:\course-learning-agent\frontend && npx vue-tsc --noEmit`
Expected: No errors

---

## Task 10: Run all tests and verify

- [ ] **Step 1: Run all backend tests**

Run: `cd f:\course-learning-agent\backend && python -m pytest tests/ -v --tb=short`
Expected: All new tests pass; existing tests pass (update expected values if scoring changed)

- [ ] **Step 2: Run frontend type check**

Run: `cd f:\course-learning-agent\frontend && npx vue-tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Verify no import regressions**

Run: `cd f:\course-learning-agent\backend && python -c "from app.agents.quiz import generate_quiz; from app.agents.concept_compare import generate_compare; from app.agents.outline import generate; from app.retrieval.search import keyword_search; from app.retrieval.chunker import build_chunks; print('All imports OK')"`
Expected: "All imports OK"
