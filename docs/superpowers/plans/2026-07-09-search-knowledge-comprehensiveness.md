# Search Quality & Knowledge Point Comprehensiveness Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 user-reported issues: (1) search returns only keyword matches with no value for single-noun queries, (2) duplicate results and low content quality, (3) knowledge points too few for a full course, (4) knowledge graph labels have inconsistent formats (sentences, chapter numbers, noise).

**Architecture:** Three-layer fix — search deduplication + snippet generation in `search.py`, knowledge point generation expansion in `llm.py`/`outline.py`, and title format normalization across all layers.

**Tech Stack:** Python (FastAPI, SQLAlchemy), Vue 3 (Element Plus), regex-based text processing

**Status:** ✅ All tasks completed and verified via browser (commit `bcd11a7`)

---

## Issue Summary

| # | Issue | Root Cause | Fix | Verification |
|---|-------|-----------|-----|-------------|
| 1 | Single-noun search has no value | Only returns raw chunk text, no context snippet | Add `generate_snippet()` with OCR noise filtering | ✅ Browser: 12 results with contextual snippets |
| 2 | Duplicate results + low quality | Same PDF uploaded twice; no dedup by filename | Dedup by `(filename, page_no)`; filter OCR noise | ✅ Browser: `has_duplicates: false` |
| 3 | Only 2-19 knowledge points for course | `_mock_outline` processes only 10-30 chunks | Process 50 chunks; add title dedup + validity filter | ✅ 25 clean knowledge points generated |
| 4 | Knowledge graph label format inconsistent | PUA chars block regex; no meta-prefix stripping | Strip PUA chars, leading noise, meta prefixes; filter sentences | ✅ 28 nodes, 0 format issues |

---

## Task 1: Search Deduplication and Snippet Generation

**Files:**
- Modify: `backend/app/retrieval/search.py` — add `_deduplicate_results()`, `generate_snippet()`
- Modify: `backend/app/schemas/search.py` — add `snippet` field to `SearchResultItem`
- Modify: `frontend/src/api/material.ts` — add `snippet` to `SearchItem` interface
- Modify: `frontend/src/views/MaterialsView.vue` — display snippet as default preview
- Test: `backend/app/tests/test_search.py`

- [x] **Step 1: Write failing test for deduplication** — `test_keyword_search_deduplicates_same_page`
- [x] **Step 2: Run test to verify it fails** — RED confirmed
- [x] **Step 3: Implement `_deduplicate_results()`** — dedup by `(filename, page_no)` to catch same PDF uploaded as different material records
- [x] **Step 4: Write failing test for snippet generation** — `test_keyword_search_includes_snippet`, `test_generate_snippet_filters_noise`
- [x] **Step 5: Implement `generate_snippet()`** — context window around keyword, filter OCR noise (PUA chars, diagram labels, IP addresses, year/chapter prefixes)
- [x] **Step 6: Add `snippet` field to `SearchResultItem` schema** — Pydantic was silently dropping the field
- [x] **Step 7: Update frontend to display snippet** — `MaterialsView.vue` shows snippet as default, full text on expand
- [x] **Step 8: Run all tests to verify they pass** — 15 tests GREEN

### Key Implementation Details

**Dedup key changed from `(material_id, page_no)` to `(filename, page_no)`:**
The same PDF was uploaded twice as separate material records (material_id 6 and 10), so dedup by material_id missed the duplicates. Using filename catches this case.

**Snippet OCR noise filtering:**
```python
_OCR_SYMBOLS = re.compile(r"[◆◇■►●○▪▫▶▷★☆▼▽▲△◼➢➣➤➔➧]")
_PUA_CHARS = re.compile(r"[\ue000-\uf8ff]")  # PPT font icons
_YEAR_CHAPTER = re.compile(r"\b\d{4}\s+(?:Chapter|Spring|Fall|Autumn|Summer)\d*\b", re.IGNORECASE)
_BRACKET_REF = re.compile(r"\[[A-Za-z]+\]")
```

---

## Task 2: Expand Knowledge Point Generation

**Files:**
- Modify: `backend/app/agents/llm.py` — `_mock_outline()` process 50 chunks (was 10→30→50)
- Modify: `backend/app/agents/outline.py` — add `_normalize_title()`, `_is_valid_concept_title()`, PUA stripping, meta-prefix stripping, title dedup

- [x] **Step 1: Write failing test for knowledge point count** — `test_mock_outline_generates_many_points`
- [x] **Step 2: Run test to verify it fails** — RED confirmed
- [x] **Step 3: Increase chunk limit** — `chunks[:10]` → `chunks[:50]`
- [x] **Step 4: Write failing test for title normalization** — `test_normalize_title_converts_questions`
- [x] **Step 5: Implement `_normalize_title()`** — strip PUA chars, leading non-alphanumeric chars, chapter/section prefixes, meta prefixes (总结/复习/回顾:), convert questions to concepts
- [x] **Step 6: Implement `_is_valid_concept_title()`** — filter sentence-style, list-style, overly long titles
- [x] **Step 7: Apply normalization + validity + dedup in `generate()`** — `seen_titles` set prevents duplicates
- [x] **Step 8: Run all tests to verify they pass** — 15 tests GREEN

### Key Implementation Details

**PUA character stripping (critical fix):**
PPT font icons are extracted as Unicode Private Use Area characters (`\uf075`, `\uf06f`). These appear at the start of titles and block regex matching for section numbers. Fix: strip PUA chars in `_clean_text()` and strip leading non-alphanumeric chars in `_normalize_title()`.

**Title normalization pipeline:**
1. `_clean_title()` — remove noise symbols, dates, page refs, chapter prefixes
2. `_normalize_title()` — strip PUA remnants, section numbers, meta prefixes; convert questions to concepts; filter chapter-only and single English words
3. `_is_valid_concept_title()` — reject sentence-style (contains "是" copula), list-style (3+ "、"), overly long (>25 chars), noise patterns

**Knowledge point count progression:** 2 → 19 → 31 → 25 (final, after filtering)

---

## Task 3: Knowledge Graph Node Filtering

**Files:**
- Modify: `backend/app/services/concept_graph_service.py` — apply `_normalize_title` + `_is_valid_concept_title` in `sync_nodes_for_user()`
- Modify: `backend/app/agents/outline.py` — expand `_NOISE_TITLE_PATTERNS`

- [x] **Step 1: Apply normalization in `sync_nodes_for_user()`** — filter noise nodes at API level, orphan cleanup deletes existing noise nodes
- [x] **Step 2: Expand `_NOISE_TITLE_PATTERNS`** — add patterns for sentence fragments, explanatory text, hex noise, incomplete fragments
- [x] **Step 3: Rebuild graph and verify** — 28 nodes, 0 format issues (no chapter prefixes, no questions, no PUA chars, no section numbers)

### Verification Results (browser_evaluate)

```json
{
  "total_nodes": 28,
  "issues": {
    "chapter_prefix": 0,
    "question_format": 0,
    "single_english": 0,
    "sentence_style": 0,
    "section_number": 0,
    "pua_chars": 0
  }
}
```

---

## Task 4: Browser Verification (agent-browser skill)

- [x] **Step 1: Verify search results** — searched "信道", got 12 results, `has_duplicates: false`, snippets clean (no OCR symbols)
- [x] **Step 2: Verify knowledge points** — 25 knowledge points, all concept-style names
- [x] **Step 3: Verify knowledge graph** — 28 nodes, 4 candidate edges, zero format issues
- [x] **Step 4: Run all tests** — 15 tests pass (5 new TDD tests)

---

## Files Modified

| File | Changes |
|------|---------|
| `backend/app/retrieval/search.py` | `_deduplicate_results()` by filename+page, `generate_snippet()` with OCR filtering |
| `backend/app/schemas/search.py` | Added `snippet` field to `SearchResultItem` |
| `frontend/src/api/material.ts` | Added `snippet` to `SearchItem` interface |
| `frontend/src/views/MaterialsView.vue` | Display snippet as default preview |
| `backend/app/agents/llm.py` | `_mock_outline` chunk limit 10→50 |
| `backend/app/agents/outline.py` | `_normalize_title()`, `_is_valid_concept_title()`, PUA stripping, meta-prefix stripping, title dedup, expanded noise patterns |
| `backend/app/services/concept_graph_service.py` | Apply normalization + validity check in `sync_nodes_for_user()` |
| `backend/app/tests/test_search.py` | 5 new TDD tests |
