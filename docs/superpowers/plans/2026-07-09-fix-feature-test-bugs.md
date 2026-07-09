# Fix 3 Functional Bugs Found in Feature Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three functional bugs discovered during systematic feature testing: (1) search keyword extraction misses ASCII terms like "TCP"/"UDP" and has no stopword filtering, (2) knowledge graph rebuild leaves orphan ConceptNodes, (3) citation verification fails on string vs int chunk_id mismatch, (4) mock outline returns hardcoded ML content ignoring the prompt.

**Architecture:** The search fix ports the proven `_keyword_set` / `_cjk_ngrams` logic from `concept_graph_service.py` into `search.py`. The graph fix adds orphan cleanup to `sync_nodes_for_user`. The citation fix adds type coercion in `verify_citations`. The mock fix parses chunk text from the prompt to generate relevant knowledge points.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / pytest.

---

## Bug Summary

| # | Bug | File | Impact |
|---|-----|------|--------|
| 1 | Search misses ASCII terms (TCP/UDP), no stopword filter | `retrieval/search.py:38-55` | Chat returns "未找到相关内容" for TCP questions despite materials containing TCP content |
| 2 | Orphan ConceptNodes not cleaned up | `services/concept_graph_service.py:111-153` | rebuild returns 0 nodes while GET returns stale orphan nodes |
| 3 | verify_citations str vs int chunk_id | `agents/course_qa.py:120-124` | Valid citations dropped when LLM returns string chunk_id |
| 4 | _mock_outline ignores prompt, returns hardcoded ML data | `agents/llm.py:159-179` | Knowledge points about "梯度下降" generated for a computer networks course |

---

### Task 1: Fix search keyword extraction (ASCII terms + stopword filtering)

**Files:**
- Modify: `backend/app/retrieval/search.py:35-55`

- [ ] **Step 1: Add stopword set and rewrite `_split_keywords`**

Replace lines 35-55 of `backend/app/retrieval/search.py`:

```python
# CJK Unified Ideographs range; used to also split Chinese queries into
# single-character keywords so multi-char terms like "快表" can still
# match chunks that only contain "表".
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")

# Common Chinese stop characters that produce too many false positives
# if used as individual LIKE keywords. Ported from
# concept_graph_service.CJK_STOP_CHARS (audit Task 6, commit 1388e91).
_CJK_STOP_CHARS = set("的是了和与及在为对中上下一种一个可以通过")


def _split_keywords(query: str) -> List[str]:
    """Split ``query`` into keywords for retrieval.

    Three extraction strategies ensure both Chinese and English queries
    produce useful search terms:

    1. **Whitespace tokens** — kept as-is (handles English queries like
       "TCP protocol header").
    2. **ASCII words (>= 2 chars)** — extracted via regex so terms like
       "TCP", "UDP", "IP" inside Chinese queries ("什么是TCP协议？")
       become searchable keywords. Without this, "TCP" is trapped inside
       the unsplit CJK string and never matches.
    3. **CJK 2-grams** — bigrams of non-stop CJK characters, so "协议"
       becomes a keyword instead of single chars "协"/"议" which match
       too broadly. Single CJK chars that are not stopwords are also
       kept as a fallback for short queries.

    All keywords are lowercased and de-duplicated (order-preserving).
    """
    if not query or not query.strip():
        return []

    # 1. Whitespace tokens
    tokens = [t for t in query.split() if t]

    # 2. ASCII words >= 2 characters (e.g. "TCP", "UDP", "HTTP")
    ascii_words = re.findall(r"[a-zA-Z]{2,}", query)

    # 3. CJK 2-grams from non-stop chars (e.g. "协议" from "什么是TCP协议？")
    cjk_chars = [
        c for c in _CJK_PATTERN.findall(query)
        if c not in _CJK_STOP_CHARS
    ]
    cjk_grams: list[str] = []
    for i in range(len(cjk_chars) - 1):
        gram = cjk_chars[i] + cjk_chars[i + 1]
        cjk_grams.append(gram)
    # Also keep single non-stop CJK chars for short queries
    cjk_grams.extend(cjk_chars)

    seen: set[str] = set()
    keywords: List[str] = []
    for kw in tokens + ascii_words + cjk_grams:
        kw_lower = kw.lower()
        if kw_lower and kw_lower not in seen:
            seen.add(kw_lower)
            keywords.append(kw_lower)
    return keywords
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd backend; .\.venv\Scripts\python.exe -c "from app.retrieval.search import _split_keywords; print(_split_keywords('什么是TCP协议？')); print(_split_keywords('UDP和TCP的区别'))"`
Expected: `['tcp', '协议', '什', '么', '是']` and `['udp', 'tcp', '区别', '和']`

- [ ] **Step 3: Run existing search tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest app/tests/test_chat_retrieval.py -v -k "search or retrieval or keyword" --no-header -q`
Expected: all pass

---

### Task 2: Fix orphan ConceptNode cleanup in sync_nodes_for_user

**Files:**
- Modify: `backend/app/services/concept_graph_service.py:111-153`

- [ ] **Step 1: Add orphan cleanup after the sync loop**

In `backend/app/services/concept_graph_service.py`, replace the `sync_nodes_for_user` function (lines 111-153) with:

```python
def sync_nodes_for_user(db: Session, user_id: int) -> int:
    """Sync KnowledgePoint -> ConceptNode for all of a user's courses.

    Idempotent: existing nodes (matched by course_id + knowledge_point_id)
    are updated in place, not duplicated. ConceptNodes whose
    KnowledgePoint has been deleted (e.g. by re-generating knowledge
    points) are removed as orphans. Returns the number of nodes.
    """
    kps = db.query(KnowledgePoint).filter_by(user_id=user_id).all()
    existing: dict[tuple[int, int], ConceptNode] = {
        (n.course_id, n.knowledge_point_id): n
        for n in db.query(ConceptNode).filter_by(user_id=user_id).all()
    }
    weak_rows = db.query(WeakPoint).filter_by(user_id=user_id).all()
    weak_kp_ids = {w.knowledge_point_id for w in weak_rows}

    # Track which ConceptNode keys are still backed by a live KP.
    live_keys: set[tuple[int, int]] = set()

    count = 0
    for kp in kps:
        key = (kp.course_id, kp.id)
        live_keys.add(key)
        node = existing.get(key)
        norm = _normalize_title(kp.title or "")
        if node is None:
            node = ConceptNode(
                user_id=user_id,
                course_id=kp.course_id,
                knowledge_point_id=kp.id,
                title=kp.title or "",
                normalized_title=norm,
                summary=kp.summary or "",
                aliases="[]",
                importance=kp.importance or 3,
                source_chunk_ids=kp.source_chunk_ids or "[]",
                weak_point_score=1.0 if kp.id in weak_kp_ids else 0.0,
            )
            db.add(node)
        else:
            node.title = kp.title or ""
            node.normalized_title = norm
            node.summary = kp.summary or ""
            node.importance = kp.importance or 3
            node.source_chunk_ids = kp.source_chunk_ids or "[]"
            node.weak_point_score = 1.0 if kp.id in weak_kp_ids else 0.0
        count += 1

    # Delete orphan ConceptNodes whose KnowledgePoint no longer exists.
    # This happens when knowledge points are re-generated (old KPs are
    # deleted in knowledge_points.py:149-152) but the derived
    # ConceptNodes were never cleaned up.
    orphan_node_ids = [
        existing[key].id
        for key in existing
        if key not in live_keys
    ]
    if orphan_node_ids:
        # Also delete edges connected to orphan nodes before removing them.
        db.query(ConceptEdge).filter(
            ConceptEdge.source_node_id.in_(orphan_node_ids)
            | ConceptEdge.target_node_id.in_(orphan_node_ids)
        ).delete(synchronize_session=False)
        db.query(ConceptNode).filter(
            ConceptNode.id.in_(orphan_node_ids)
        ).delete(synchronize_session=False)

    db.flush()
    return count
```

- [ ] **Step 2: Run existing concept graph tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest app/tests/test_concept_graph_service.py -v --no-header -q`
Expected: all pass

---

### Task 3: Fix verify_citations type compatibility (str vs int chunk_id)

**Files:**
- Modify: `backend/app/agents/course_qa.py:111-125`

- [ ] **Step 1: Add type coercion to verify_citations**

Replace the `verify_citations` function (lines 111-125) in `backend/app/agents/course_qa.py`:

```python
def verify_citations(
    output: dict[str, Any], retrieved_chunks: list[dict]
) -> list[dict]:
    """Drop citations whose ``chunk_id`` is not in ``retrieved_chunks``.

    Returns the filtered citation list. This is the CitationVerifier:
    it prevents the LLM from referencing chunks that were never
    retrieved (fabricated references).

    Type coercion: LLMs sometimes return ``chunk_id`` as a string
    (e.g. ``"5"``) even though the database stores integers. We coerce
    both sides to ``int`` so valid citations are not mistakenly dropped.
    """
    valid_ids: set[int] = set()
    for chunk in retrieved_chunks:
        try:
            valid_ids.add(int(chunk["chunk_id"]))
        except (TypeError, ValueError):
            continue

    def _to_int(cid: Any) -> int | None:
        try:
            return int(cid)
        except (TypeError, ValueError):
            return None

    result: list[dict] = []
    for cite in output.get("citations", []):
        cid = _to_int(cite.get("chunk_id"))
        if cid is not None and cid in valid_ids:
            cite["chunk_id"] = cid  # normalise to int
            result.append(cite)
    return result
```

- [ ] **Step 2: Run existing course_qa tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest app/tests/test_course_qa_agent.py -v --no-header -q`
Expected: all pass

---

### Task 4: Fix _mock_outline to extract real content from prompt

**Files:**
- Modify: `backend/app/agents/llm.py:159-179`

- [ ] **Step 1: Rewrite `_mock_outline` to parse chunk text from the prompt**

Replace the `_mock_outline` function (lines 159-179) in `backend/app/agents/llm.py`:

```python
def _mock_outline(prompt: str = "") -> dict[str, Any]:
    """Generate knowledge points from the prompt's chunk content.

    The mock previously returned hardcoded ML knowledge points regardless
    of the course content. Now it extracts chunk text from the prompt
    (which outline.py correctly fills with real course material) and
    generates knowledge points from the first sentences of each chunk.
    """
    import re as _re

    # Extract chunk text from the prompt. The outline prompt formats
    # chunks as: [片段N] chunk_id=...\n<text>
    chunk_pattern = _re.compile(
        r"\[片段\d+\]\s*chunk_id=\d+[^\n]*\n(.+?)(?=\n\n|\Z)",
        _re.DOTALL,
    )
    chunks = chunk_pattern.findall(prompt)

    if not chunks:
        # No chunks in prompt — return empty so the caller can handle it
        return {"knowledge_points": []}

    knowledge_points: list[dict[str, Any]] = []
    for i, chunk_text in enumerate(chunks[:5]):  # max 5 points
        # Use the first non-empty line as the title (often a heading)
        lines = [
            line.strip()
            for line in chunk_text.strip().split("\n")
            if line.strip()
        ]
        title = lines[0][:60] if lines else f"知识点{i + 1}"
        # Use first 100 chars as summary
        summary = chunk_text.strip()[:100].replace("\n", " ")

        knowledge_points.append({
            "title": title,
            "summary": summary,
            "importance": 5 if i == 0 else 4,
            "source_chunk_ids": [i + 1],
            "exam_style": "简答题/选择题",
            "review_action": f"重读片段{i + 1}的相关内容。",
        })

    return {"knowledge_points": knowledge_points}
```

- [ ] **Step 2: Run existing LLM tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest app/tests/test_llm.py -v --no-header -q`
Expected: all pass (mock tests may need updating if they assert hardcoded titles)

---

### Task 5: Full regression test + commit

**Files:** none (verification + commit only)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q`
Expected: all pass

- [ ] **Step 2: Commit with the git-commit skill**

Files to stage:
- `backend/app/retrieval/search.py`
- `backend/app/services/concept_graph_service.py`
- `backend/app/agents/course_qa.py`
- `backend/app/agents/llm.py`

---

### Task 6: Verify fixes with API tests

**Files:** none (runtime verification)

- [ ] **Step 1: Restart backend and re-run targeted API tests**

- [ ] **Step 2: Verify search now finds TCP content**

- [ ] **Step 3: Verify knowledge points are relevant to course content**

- [ ] **Step 4: Verify knowledge graph rebuild cleans orphans**

---

## Self-Review

**1. Spec coverage:**
- Search missing TCP/UDP → Task 1 (ASCII extraction + stopword filter). ✓
- Orphan ConceptNodes → Task 2 (cleanup in sync_nodes_for_user). ✓
- Citation type mismatch → Task 3 (int coercion in verify_citations). ✓
- Mock outline hardcoded ML → Task 4 (parse prompt chunks). ✓
- Full regression → Task 5. ✓
- Runtime verification → Task 6. ✓

**2. Placeholder scan:** No TBD/TODO present. Every code step shows actual code. ✓

**3. Type consistency:** `_split_keywords` returns `List[str]` (lowercased). `verify_citations` returns `list[dict]` with `chunk_id` normalised to `int`. `sync_nodes_for_user` returns `int` (node count). `_mock_outline` returns `dict[str, Any]` with `knowledge_points` list matching the schema in `outline.py:174`. ✓
