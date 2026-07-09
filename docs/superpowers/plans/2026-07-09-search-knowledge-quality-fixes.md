# Search Relevance & Knowledge Point Quality Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 user-reported quality issues: irrelevant search results, overly broad knowledge points, noise symbols in descriptions, irrelevant content in learning page, and inconsistent knowledge graph labels.

**Architecture:** Multi-layer approach — backend search scoring (density-based), backend knowledge point post-processing (cleaning + filtering), frontend display cleaning (inline noise removal + label cleaning), and mock LLM title extraction improvements.

**Tech Stack:** Python (FastAPI, SQLAlchemy), Vue 3 (Element Plus), regex-based text cleaning

---

## Issue Summary

| # | Issue | Root Cause | Fix Location |
|---|-------|-----------|--------------|
| 1 | Search returns irrelevant results ("信道" matches "通信") | `_split_keywords` generates single CJK chars alongside bigrams | `backend/app/retrieval/search.py` |
| 2 | Knowledge points too broad ("数据链路层") | No granularity rules in prompt; no post-processing filter | `outline_v1.md` + `outline.py` |
| 3 | Noise symbols (□, dates, page refs) in descriptions | No text cleaning after LLM output | `outline.py` `_clean_text()` |
| 4 | Learning page shows "2026" and messy formatting | Noise embedded inline (page# + date concatenated) | `LearnView.vue` `INLINE_NOISE_PATTERNS` |
| 5 | Knowledge graph labels too large, format inconsistent | No display-level label cleaning | `KnowledgeGraphView.vue` `cleanNodeLabel()` |

---

## Task 1: Fix Search Keyword Splitting (Issue 1)

**Files:**
- Modify: `backend/app/retrieval/search.py` — `_split_keywords()` function

**Root cause:** The function generated CJK bigrams AND individual characters. Searching "信道" produced keywords `["信道", "信", "道"]`, causing "信" to match "通信" (false positive).

- [x] **Step 1: Remove single-char fallback when bigrams exist**

```python
# Before: cjk_grams.extend(cjk_chars)  # always adds single chars
# After:
if not cjk_grams:
    cjk_grams.extend(cjk_chars)  # only for single-char queries
```

- [x] **Step 2: Tune density scoring coefficients**

Changed from `(density * 0.04) + (coverage * 0.3)` to `(density * 0.02) + (coverage * 0.2) + title_bonus(0.15)` to ensure title-matching chunks rank above body-only matches even for short texts.

- [x] **Step 3: Verify search results**

Searched "信道" — all 12 results contain "信道" directly. No false positives from "通信" or other single-char matches. Previously irrelevant results ("端系统之间的通信", "识别比特流信息") eliminated.

---

## Task 2: Knowledge Point Granularity & Cleaning (Issues 2+3)

**Files:**
- Modify: `backend/app/agents/prompts/outline_v1.md` — add granularity rules
- Modify: `backend/app/agents/outline.py` — add `_clean_text()`, `_clean_title()`, `_TOO_BROAD_TITLES`, `_NOISE_TITLE_PATTERNS`

- [x] **Step 1: Add granularity rules to prompt**

Added "知识点粒度规则" section with correct/wrong examples:
- Wrong: "数据链路层" (too broad)
- Correct: "CSMA/CD协议的工作原理" (specific concept)

- [x] **Step 2: Implement `_clean_text()` for noise removal**

```python
_NOISE_SYMBOLS = re.compile(r"[□☐◆■►●○▪▫▶▷◇★☆▼▽▲△]")
_DATE_PATTERN = re.compile(r"\d{4}年(?:\d+月)?(?:春|秋|夏|冬)?")
_PAGE_REF = re.compile(r"第\d+页|P\d+|\[[A-Za-z]+\]")
_META_INFO = re.compile(r"网络空间安全学院|计算机(?:网络|操作系统|数据结构|数据库)")
```

- [x] **Step 3: Implement `_clean_title()` with prefix stripping**

Strips chapter prefixes ("第五章 → "), section numbers ("5.1.3 → "), year numbers, and dedup suffixes ("（4）→ ").

- [x] **Step 4: Add `_TOO_BROAD_TITLES` filter set**

Filters chapter-level titles: "数据链路层", "物理层", "网络层", "信道", "帧", "协议", etc.

- [x] **Step 5: Add `_NOISE_TITLE_PATTERNS` for data noise**

Filters: IP addresses, pure-number titles, year-prefixed titles, figure/table references ("标题5...", "图5-...", "表5-..."), router labels ("R3 R2"), pure-English multi-word titles.

---

## Task 3: Learning Page Content Filtering (Issue 4)

**Files:**
- Modify: `frontend/src/views/LearnView.vue` — `INLINE_NOISE_PATTERNS`, `cleanChunkText()`, `isUsefulChunk()`

- [x] **Step 1: Add `INLINE_NOISE_PATTERNS` for inline cleaning**

```typescript
const INLINE_NOISE_PATTERNS = [
  /\d{4}年(?:\d+月)?(?:春|秋|夏|冬)?/g,   // dates: "2026年春"
  /\[Forouzan\]/gi,
  /\[Tanenbaum\]/gi,
  /\[谢\]/g,
]
```

- [x] **Step 2: Update `cleanChunkText()` to apply inline removal**

Lines surviving line-level filtering are further cleaned by removing inline date/ref patterns. "42026年春" → "4" (date stripped inline).

- [x] **Step 3: Update `isUsefulChunk()` to detect inline noise**

Counts lines with inline noise as noise lines, improving the noise ratio calculation.

- [x] **Step 4: Verify "2026" removal**

Before: 26 chunks contained "2026". After: 0 chunks contain "2026".

---

## Task 4: Knowledge Graph Label Cleaning (Issue 5)

**Files:**
- Modify: `frontend/src/views/KnowledgeGraphView.vue` — `cleanNodeLabel()`

- [x] **Step 1: Implement `cleanNodeLabel()` with multi-pattern cleaning**

Removes: noise symbols, dates (with/without 年), page refs, chapter prefixes ("第五章 → "), section numbers ("1.1.3 → "), standalone years, and bibliographic tags.

- [x] **Step 2: Apply in template**

Changed `{{ node.title }}` to `{{ cleanNodeLabel(node.title) }}` in the SVG node label.

- [x] **Step 3: Verify labels**

After cleaning: 0 noise symbols, 0 dates, 0 years, 0 chapter prefixes. "第9章 磁盘存储器管理" → "磁盘存储器管理", "2026 Chapter3 Transport Layer" → "Chapter3 Transport Layer" (then filtered by outline.py).

---

## Task 5: Mock LLM Title Extraction Improvements

**Files:**
- Modify: `backend/app/agents/llm.py` — `_extract_title_from_chunk()`, `_mock_outline()`

- [x] **Step 1: Add META_LINE_RE for figure/table/meta references**

```python
META_LINE_RE = re.compile(r"^(标题\d|图\d|表\d|第\d+行|第\d+图)")
```

- [x] **Step 2: Strip chapter prefix in `_extract_title_from_chunk` Strategy 1**

"第五章 数据链路层" → strips prefix → "数据链路层" (then filtered by outline.py as too broad).

- [x] **Step 3: Add minimum length filter (≥4 chars)**

Filters very short noise like "R3 R2", "表5-1中".

- [x] **Step 4: Filter DB chunk titles with meta patterns in `_mock_outline`**

DB titles matching META_LINE_RE or containing year keywords are skipped, falling back to `_extract_title_from_chunk`.

- [x] **Step 5: Process 10 chunks instead of 5**

Increased from `chunks[:5]` to `chunks[:10]` for more knowledge point coverage.

---

## Verification Results

| Check | Before | After |
|-------|--------|-------|
| Search "信道" false positives | "通信", "识别比特流" appeared | All 12 results contain "信道" |
| Learning page "2026" occurrences | 26 chunks | 0 chunks |
| Knowledge graph noise symbols | Present (□, ◆, etc.) | 0 |
| Knowledge graph chapter prefixes | "第五章 数据链路层" | "数据链路层" (prefix stripped) |
| Knowledge point titles | "数据链路层" (too broad) | "为什么需要数据链路层？" (specific) |
| Backend tests | 350 passed | All search + LLM tests pass |
