# Search Quality & Knowledge Point Comprehensiveness Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 user-reported issues: (1) search returns only keyword matches with no value for single-noun queries, (2) duplicate results and low content quality, (3) knowledge points too few for a full course, (4) knowledge graph labels have inconsistent formats (sentences, chapter numbers, noise).

**Architecture:** Three-layer fix — search deduplication + snippet generation in `search.py`, knowledge point generation expansion in `llm.py`/`outline.py`, and title format normalization across all layers.

**Tech Stack:** Python (FastAPI, SQLAlchemy), Vue 3 (Element Plus), regex-based text processing

---

## Issue Summary

| # | Issue | Root Cause | Fix |
|---|-------|-----------|-----|
| 1 | Single-noun search has no value | Only returns raw chunk text, no context snippet | Add `generate_snippet()` with keyword context window |
| 2 | Duplicate results + low quality | No dedup by page; OCR noise in snippets | Dedup by `(material_id, page_no)`; filter noise from snippets |
| 3 | Only 2 knowledge points for entire course | `_mock_outline` processes only 10 chunks; over-aggressive filtering | Process all chunks; relax filters; smarter title extraction |
| 4 | Knowledge graph label format inconsistent | No title normalization; chapter numbers and noise pass through | Add `_normalize_title()` to convert questions → concepts, filter chapter-only/noise |

---

## Task 1: Search Deduplication and Snippet Generation

**Files:**
- Modify: `backend/app/retrieval/search.py` — add `_deduplicate_results()`, `generate_snippet()`
- Test: `backend/app/tests/test_search.py`

- [ ] **Step 1: Write failing test for deduplication**

```python
def test_keyword_search_deduplicates_same_page(client, tmp_path, monkeypatch):
    """Search results from the same page are deduplicated."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))
    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)
    from app.api.deps import get_db
    from app.main import app
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        results = keyword_search(db, course_id, "TLB", top_k=12)
        # No two results should have the same (material_id, page_no)
        seen_pages = set()
        for r in results:
            key = (r["material_id"], r["page_no"])
            assert key not in seen_pages, f"Duplicate page: {key}"
            seen_pages.add(key)
    finally:
        db.close()
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement `_deduplicate_results()`**

```python
def _deduplicate_results(results: list[dict]) -> list[dict]:
    """Remove duplicate results from the same (material_id, page_no).
    
    When multiple chunks from the same page match, keep only the
    highest-scoring one to avoid redundant results.
    """
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in results:
        key = (r.get("material_id"), r.get("page_no"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped
```

- [ ] **Step 4: Write failing test for snippet generation**

```python
def test_keyword_search_includes_snippet(client, tmp_path, monkeypatch):
    """Search results include a 'snippet' field with keyword context."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))
    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)
    from app.api.deps import get_db
    from app.main import app
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        results = keyword_search(db, course_id, "TLB", top_k=12)
        for r in results:
            assert "snippet" in r
            assert len(r["snippet"]) <= 200
            # Snippet should contain the keyword or be derived from text
            assert len(r["snippet"]) > 0
    finally:
        db.close()
```

- [ ] **Step 5: Implement `generate_snippet()`**

```python
def generate_snippet(text: str, keywords: list[str], max_len: int = 150) -> str:
    """Extract a context snippet around the first keyword match.
    
    Filters out noise lines (IP addresses, page numbers, single letters)
    and returns a clean snippet centered on the keyword.
    """
    if not text:
        return ""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # Filter noise lines
    NOISE_LINE = re.compile(r"^[\d\s\.\-:]+$|^[A-Z]\s+[A-Z]\s|^第\d+页|^P\d+")
    clean_lines = [l for l in lines if not NOISE_LINE.match(l) and len(l) >= 3]
    if not clean_lines:
        return text[:max_len]
    
    # Find the first line containing a keyword
    kw_lower = [k.lower() for k in keywords]
    match_idx = 0
    for i, line in enumerate(clean_lines):
        line_lower = line.lower()
        if any(kw in line_lower for kw in kw_lower):
            match_idx = i
            break
    
    # Take 2 lines before and 2 after the match for context
    start = max(0, match_idx - 1)
    end = min(len(clean_lines), match_idx + 3)
    snippet = " ".join(clean_lines[start:end])
    if len(snippet) > max_len:
        # Center on the keyword
        kw_pos = snippet.lower().find(kw_lower[0]) if kw_lower else 0
        half = max_len // 2
        start_pos = max(0, kw_pos - half)
        snippet = snippet[start_pos:start_pos + max_len]
    return snippet.strip()
```

- [ ] **Step 6: Run all tests to verify they pass**

---

## Task 2: Expand Knowledge Point Generation

**Files:**
- Modify: `backend/app/agents/llm.py` — `_mock_outline()` process all chunks
- Modify: `backend/app/agents/outline.py` — relax filtering, add `_normalize_title()`

- [ ] **Step 1: Write failing test for knowledge point count**

```python
def test_mock_outline_generates_many_points():
    """Mock outline should generate knowledge points from all chunks, not just 10."""
    from app.agents.llm import _mock_outline
    # Build a prompt with 20 chunks
    chunks = []
    for i in range(20):
        chunks.append(f"[片段{i+1}] chunk_id={i+1}，标题：概念{i+1}\n这是第{i+1}个知识点的详细内容，包含重要概念和定义。")
    prompt = "\n\n".join(chunks)
    result = _mock_outline(prompt)
    points = result.get("knowledge_points", [])
    assert len(points) >= 10, f"Expected >= 10 points, got {len(points)}"
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Change `chunks[:10]` to process all chunks**

In `_mock_outline`, change `for i, chunk_text in enumerate(chunks[:10]):` to process all chunks but cap at 30 to avoid excessive output.

- [ ] **Step 4: Write failing test for title normalization**

```python
def test_normalize_title_converts_questions():
    """Questions like '为什么需要数据链路层?' should become concept phrases."""
    from app.agents.outline import _normalize_title
    assert _normalize_title("为什么需要数据链路层?") == "数据链路层的必要性"
    assert _normalize_title("什么是CSMA/CD协议?") == "CSMA/CD协议"
    assert _normalize_title("虚拟存储器") == "虚拟存储器"  # already a concept
    assert _normalize_title("第10章") == ""  # chapter number filtered
    assert _normalize_title("Date") == ""  # English noise filtered
```

- [ ] **Step 5: Implement `_normalize_title()`**

```python
def _normalize_title(title: str) -> str:
    """Normalize a knowledge point title to a concept phrase.
    
    - "为什么需要X?" → "X的必要性"
    - "什么是X?" → "X"  
    - "第N章" → "" (filtered)
    - Single English words → "" (filtered)
    """
    if not title:
        return ""
    # Filter chapter-number-only titles
    if re.match(r"^第[\d一二三四五六七八九十]+章$", title):
        return ""
    # Filter single English words (noise like "Date")
    if re.match(r"^[A-Za-z]{1,10}$", title):
        return ""
    # Convert "为什么需要X?" → "X的必要性"
    m = re.match(r"^为什么需要(.+?)\??$", title)
    if m:
        return f"{m.group(1)}的必要性"
    # Convert "什么是X?" → "X"
    m = re.match(r"^什么是(.+?)\??$", title)
    if m:
        return m.group(1)
    # Convert "为什么X?" → "X的原因"
    m = re.match(r"^为什么(.+?)\??$", title)
    if m:
        return f"{m.group(1)}的原因"
    return title
```

- [ ] **Step 6: Apply `_normalize_title()` in `generate()` post-processing**

- [ ] **Step 7: Run all tests to verify they pass**

---

## Task 3: Knowledge Graph Node Filtering

**Files:**
- Modify: `backend/app/agents/outline.py` — ensure `_normalize_title` + filters apply to graph nodes
- Modify: `frontend/src/views/KnowledgeGraphView.vue` — filter out empty/invalid labels

- [ ] **Step 1: Ensure knowledge graph rebuild uses same title normalization**

- [ ] **Step 2: Add frontend filter for invalid node labels**

In `KnowledgeGraphView.vue`, filter nodes where `cleanNodeLabel(title)` returns empty or is too short.

- [ ] **Step 3: Verify via browser**
