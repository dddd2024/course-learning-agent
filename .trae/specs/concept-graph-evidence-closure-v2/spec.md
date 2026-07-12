# 跨课程知识图谱证据约束型成熟版 v2 补强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把跨课程知识图谱从"证据约束雏形版"（commit 06bc8b8）补强为"证据约束型成熟版"——mock 环境也能产出 citation、compare 缓存按 user_focus/evidence_hash 细化、user_focus 进入 prompt、mismatched edge 返回 400、验收脚本静态检查补强、CI artifacts 实际产出。

**Architecture:** 在现有 ConceptNode/ConceptEdge/ConceptCompareReport 三层模型上，修改 LLM 适配层（新增 concept_compare mock builder）、compare service（缓存粒度、evidence_hash、user_focus、BAD_REQUEST 区分）、compare agent（user_focus 进入 prompt）、endpoint（异常区分）、前端（user_focus 选择器），不引入新模型、不引入图数据库。

**Tech Stack:** Python / FastAPI / SQLAlchemy / pytest / Vue 3 / Element Plus / GitHub Actions

**基线:** 06bc8b8 (origin/main)

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `backend/app/agents/llm.py` | 新增 `_mock_concept_compare` builder；注册到 `_MOCK_BUILDERS`；builder 接收 prompt 参数 | 修改 |
| `backend/app/agents/prompts/concept_compare_v1.md` | prompt 增加 user_focus 占位符 | 修改 |
| `backend/app/agents/concept_compare.py` | generate_compare 传入 user_focus 到 prompt | 修改 |
| `backend/app/models/concept_graph.py` | ConceptCompareReport 增加 user_focus、evidence_hash 列 | 修改 |
| `backend/app/services/concept_compare_service.py` | 缓存按 user_focus+evidence_hash 过滤；mismatched edge 抛 BusinessException | 修改 |
| `backend/app/api/v1/endpoints/concept_graph.py` | compare endpoint 区分 None(404) 与 BusinessException(400) | 修改 |
| `backend/app/tests/test_concept_compare_agent.py` | mock citation、user_focus prompt、缓存粒度、mismatched 400 测试 | 修改 |
| `backend/app/tests/test_concept_graph_api.py` | mismatched edge 400 统一错误格式测试 | 修改 |
| `frontend/src/api/conceptGraph.ts` | compareNodes 接收 user_focus 参数 | 修改 |
| `frontend/src/views/KnowledgeGraphView.vue` | compare drawer 增加 user_focus 选择器 | 修改 |
| `scripts/verify_phase2_engineering.ps1` | 第 12 节：mock builder、evidence_chunks=[] 禁用、user_focus 检查 | 修改 |
| `scripts/verify_phase2_engineering.sh` | 同上 Linux 版 | 修改 |

---

## Task 1: concept_compare mock builder 产出 citation (P0)

**Files:**
- Modify: `backend/app/agents/llm.py`
- Test: `backend/app/tests/test_concept_compare_agent.py`

- [ ] **Step 1: 写失败测试 — mock 模式给 evidence 时返回 citation**

在 `test_concept_compare_agent.py` 末尾追加：

```python
def test_concept_compare_mock_returns_citations_when_evidence_given(db_session):
    """mock 模式下，给 evidence_chunks 时 generate_compare 必须返回 citation。"""
    from app.models import MaterialChunk

    user, n1, n2 = _setup_two_nodes(db_session)
    ch1 = MaterialChunk(
        material_id=1, course_id=n1.course_id, chunk_index=0,
        title="OS死锁证据", page_no=1, text="资源循环等待是死锁的关键特征",
    )
    ch2 = MaterialChunk(
        material_id=1, course_id=n2.course_id, chunk_index=0,
        title="DB死锁证据", page_no=1, text="事务锁冲突是死锁的关键特征",
    )
    db_session.add_all([ch1, ch2])
    db_session.commit()
    n1.source_chunk_ids = json.dumps([ch1.id])
    n2.source_chunk_ids = json.dumps([ch2.id])
    db_session.commit()

    # 不 monkeypatch generate_compare，走真实 mock LLM 路径
    result = generate_compare(
        db_session, user.id,
        concept_a={"title": n1.title, "summary": n1.summary or ""},
        concept_b={"title": n2.title, "summary": n2.summary or ""},
        evidence_chunks=[
            {"chunk_id": ch1.id, "course_id": n1.course_id, "text": "资源循环等待"},
            {"chunk_id": ch2.id, "course_id": n2.course_id, "text": "事务锁冲突"},
        ],
    )
    assert result["citation_chunk_ids"], "mock 模式有证据时必须返回 citation"
    assert ch1.id in result["citation_chunk_ids"]
    assert ch2.id in result["citation_chunk_ids"]
```

在文件顶部 `import json` 之后追加（若尚无）：
```python
import json
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py::test_concept_compare_mock_returns_citations_when_evidence_given -v`
Expected: FAIL — `assert [] is not empty`（mock builder 未注册，走 `_mock_fallback` 返回空 citation）

- [ ] **Step 3: 实现 — 新增 _mock_concept_compare builder 并注册**

在 `llm.py` 中：

3a. 在文件顶部 `import json` 之后追加：
```python
import re
```

3b. 修改 `_mock_response` 与 builder 签名，让 builder 接收 prompt：

将
```python
def _mock_response(agent_type: str) -> dict[str, Any]:
    """Return a deterministic, structurally-valid payload for ``agent_type``."""
    builder = _MOCK_BUILDERS.get(agent_type)
    if builder is None:
        # Unknown agent types get a minimal generic envelope so callers
        # still receive valid JSON.
        return {"agent_type": agent_type, "result": {}}
    return builder()
```
替换为：
```python
def _mock_response(
    agent_type: str, prompt: str = ""
) -> dict[str, Any]:
    """Return a deterministic, structurally-valid payload for ``agent_type``."""
    builder = _MOCK_BUILDERS.get(agent_type)
    if builder is None:
        # Unknown agent types get a minimal generic envelope so callers
        # still receive valid JSON.
        return {"agent_type": agent_type, "result": {}}
    return builder(prompt)
```

3c. 给 7 个现有 builder 的签名都加上 `prompt: str = ""` 参数（函数体不变）。例如：
```python
def _mock_course_qa(prompt: str = "") -> dict[str, Any]:
```
对 `_mock_outline`、`_mock_planner`、`_mock_task_decompose`、`_mock_multi_course_schedule`、`_mock_quiz_generate`、`_mock_citation_verify` 都做同样修改。

3d. 修改 `call_llm_with_meta` 中两处 `_mock_response(agent_type)` 调用，改为 `_mock_response(agent_type, prompt)`：
- 第 85 行：`return _mock_response(agent_type), {` → `return _mock_response(agent_type, prompt), {`
- 第 105 行：`return _mock_response(agent_type), {` → `return _mock_response(agent_type, prompt), {`
- 第 112 行：`return _mock_response(agent_type), {` → `return _mock_response(agent_type, prompt), {`

3e. 在 `_mock_citation_verify` 函数之后、`_MOCK_BUILDERS = {` 之前，新增 builder：
```python
def _mock_concept_compare(prompt: str = "") -> dict[str, Any]:
    """Mock concept_compare: return citations derived from evidence in the prompt.

    The prompt contains a ``证据片段: [...]`` line whose JSON array lists
    the evidence chunks. We parse it so the mock returns real chunk ids
    rather than empty citations.
    """
    chunk_ids: list[int] = []
    m = re.search(r"证据片段:\s*(\[.*\])", prompt)
    if m:
        try:
            chunks = json.loads(m.group(1))
            for c in chunks:
                if isinstance(c, dict) and "chunk_id" in c:
                    try:
                        chunk_ids.append(int(c["chunk_id"]))
                    except (TypeError, ValueError):
                        continue
        except (json.JSONDecodeError, TypeError):
            pass
    citations = [
        {"chunk_id": cid, "quote": f"证据片段 {cid}", "supports": "对比依据"}
        for cid in chunk_ids
    ]
    return {
        "concept_a": {"title": "概念 A", "explanation": "基于证据的概念 A 解析"},
        "concept_b": {"title": "概念 B", "explanation": "基于证据的概念 B 解析"},
        "similarities": ["两者在各自课程中均为核心概念"],
        "differences": [
            {"dimension": "所属课程", "a": "课程 A", "b": "课程 B"}
        ],
        "transfer_learning": ["可迁移的方法论"],
        "confusions": ["注意适用场景差异"],
        "exam_questions": ["简述两者的联系与区别"],
        "citations": citations,
        "insufficient_evidence": not bool(citations),
    }
```

3f. 在 `_MOCK_BUILDERS` 字典中追加一项：
```python
_MOCK_BUILDERS = {
    "course_qa": _mock_course_qa,
    "outline": _mock_outline,
    "planner": _mock_planner,
    "task_decompose": _mock_task_decompose,
    "multi_course_schedule": _mock_multi_course_schedule,
    "quiz_generate": _mock_quiz_generate,
    "citation_verify": _mock_citation_verify,
    "concept_compare": _mock_concept_compare,
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py -v`
Expected: 全部 PASS（含新测试）

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/llm.py backend/app/tests/test_concept_compare_agent.py
git commit -m "feat(llm): add concept_compare mock builder that emits citations from evidence"
```

---

## Task 2: user_focus 进入 prompt (P1)

**Files:**
- Modify: `backend/app/agents/prompts/concept_compare_v1.md`
- Modify: `backend/app/agents/concept_compare.py`
- Test: `backend/app/tests/test_concept_compare_agent.py`

- [ ] **Step 1: 写失败测试 — user_focus 出现在 prompt**

在 `test_concept_compare_agent.py` 末尾追加：
```python
def test_compare_prompt_contains_user_focus(db_session, monkeypatch):
    """user_focus 必须进入 prompt，不允许只是请求字段。"""
    user, n1, n2 = _setup_two_nodes(db_session)
    captured = {}

    def fake_call_llm_with_meta(prompt, agent_type, schema=None, user_config=None):
        captured["prompt"] = prompt
        return (
            {
                "concept_a": {"title": "A", "explanation": "x"},
                "concept_b": {"title": "B", "explanation": "y"},
                "similarities": [], "citations": [],
            },
            {"provider": "mock", "fallback_used": False,
             "fallback_reason": None, "model_name": "mock"},
        )

    monkeypatch.setattr(
        "app.agents.concept_compare.call_llm_with_meta", fake_call_llm_with_meta
    )
    generate_compare(
        db_session, user.id,
        concept_a={"title": n1.title, "summary": n1.summary or ""},
        concept_b={"title": n2.title, "summary": n2.summary or ""},
        evidence_chunks=[],
        user_focus="exam",
    )
    assert "exam" in captured["prompt"], "user_focus 必须出现在 prompt 中"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py::test_compare_prompt_contains_user_focus -v`
Expected: FAIL — `"exam" not in prompt`

- [ ] **Step 3: 实现 — prompt 模板增加 user_focus**

3a. 修改 `concept_compare_v1.md`，在 `证据片段: {evidence}` 之后加一行：
```markdown
你是一个跨课程概念对比助手。请基于给定的证据片段，生成结构化对比报告。

概念 A: {concept_a_title}
概念 A 摘要: {concept_a_summary}
概念 B: {concept_b_title}
概念 B 摘要: {concept_b_summary}
证据片段: {evidence}
用户关注点: {user_focus}

请输出严格的 JSON，包含以下字段:
{{
  "concept_a": {{"title": "...", "explanation": "..."}},
  "concept_b": {{"title": "...", "explanation": "..."}},
  "similarities": ["..."],
  "differences": [{{"dimension": "...", "a": "...", "b": "..."}}],
  "transfer_learning": ["..."],
  "confusions": ["..."],
  "exam_questions": ["..."],
  "citations": [{{"chunk_id": 0, "quote": "...", "supports": "..."}}]
}}

约束:
- 只能基于给定的证据片段生成，不得引入未给出的资料事实。
- 如果证据不足，添加 "insufficient_evidence": true。
- 用户关注点为 concept（概念理解）/exam（考试复习）/confusion（易混点对比），请据此调整侧重。
- 输出必须是合法 JSON。
```

3b. 修改 `backend/app/agents/concept_compare.py` 的 `generate_compare`：

将
```python
        prompt = prompt_template.format(
            concept_a_title=concept_a.get("title", ""),
            concept_a_summary=concept_a.get("summary", ""),
            concept_b_title=concept_b.get("title", ""),
            concept_b_summary=concept_b.get("summary", ""),
            evidence=evidence_text,
        )
```
替换为：
```python
        prompt = prompt_template.format(
            concept_a_title=concept_a.get("title", ""),
            concept_a_summary=concept_a.get("summary", ""),
            concept_b_title=concept_b.get("title", ""),
            concept_b_summary=concept_b.get("summary", ""),
            evidence=evidence_text,
            user_focus=user_focus,
        )
```

并在 `generate_compare` 函数签名增加 `user_focus: str = "concept"` 参数：
```python
def generate_compare(
    db,
    user_id: int,
    concept_a: dict,
    concept_b: dict,
    evidence_chunks: list[dict] | None = None,
    user_config: dict | None = None,
    user_focus: str = "concept",
) -> dict:
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/prompts/concept_compare_v1.md backend/app/agents/concept_compare.py backend/app/tests/test_concept_compare_agent.py
git commit -m "feat(compare): thread user_focus into compare prompt"
```

---

## Task 3: compare service 传 user_focus 给 agent (P1)

**Files:**
- Modify: `backend/app/services/concept_compare_service.py`
- Test: `backend/app/tests/test_concept_compare_agent.py`

- [ ] **Step 1: 写失败测试 — service 把 user_focus 传给 generate_compare**

在 `test_concept_compare_agent.py` 末尾追加：
```python
def test_compare_service_passes_user_focus(db_session, monkeypatch):
    """compare service 必须把 user_focus 传给 generate_compare。"""
    from app.services.concept_compare_service import get_or_create_compare_report

    user, n1, n2 = _setup_two_nodes(db_session)
    captured = {}

    def fake_generate(db, uid, concept_a, concept_b, evidence_chunks=None,
                      user_config=None, user_focus="concept"):
        captured["user_focus"] = user_focus
        return {
            "report_json": {"concept_a": {}, "concept_b": {}, "similarities": []},
            "citation_chunk_ids": [],
            "provider": "mock",
            "model_name": "mock",
            "fallback_used": False,
            "fallback_reason": "",
            "audit_run_id": 1,
        }

    monkeypatch.setattr(
        "app.services.concept_compare_service.generate_compare", fake_generate
    )
    get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id, user_focus="exam"
    )
    assert captured["user_focus"] == "exam"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py::test_compare_service_passes_user_focus -v`
Expected: FAIL — `KeyError: 'user_focus'`（fake_generate 收不到 user_focus，因为 service 没传）

- [ ] **Step 3: 实现 — service 传 user_focus**

在 `concept_compare_service.py` 的 `get_or_create_compare_report` 中，将 `generate_compare(...)` 调用改为：
```python
    result = generate_compare(
        db,
        user_id,
        concept_a={"title": n1.title, "summary": n1.summary or ""},
        concept_b={"title": n2.title, "summary": n2.summary or ""},
        evidence_chunks=evidence_chunks,
        user_config=user_config,
        user_focus=user_focus,
    )
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/concept_compare_service.py backend/app/tests/test_concept_compare_agent.py
git commit -m "feat(compare): pass user_focus from service to compare agent"
```

---

## Task 4: ConceptCompareReport 增加 user_focus + evidence_hash 列 (P1)

**Files:**
- Modify: `backend/app/models/concept_graph.py`
- Modify: `backend/app/services/concept_compare_service.py`
- Test: `backend/app/tests/test_concept_compare_agent.py`

- [ ] **Step 1: 写失败测试 — 缓存按 user_focus 分离**

在 `test_concept_compare_agent.py` 末尾追加：
```python
def test_compare_cache_separates_user_focus(db_session, monkeypatch):
    """不同 user_focus 不应复用同一份缓存报告。"""
    from app.services.concept_compare_service import get_or_create_compare_report

    user, n1, n2 = _setup_two_nodes(db_session)
    call_count = {"n": 0}

    def fake_generate(db, uid, concept_a, concept_b, evidence_chunks=None,
                      user_config=None, user_focus="concept"):
        call_count["n"] += 1
        return {
            "report_json": {"user_focus": user_focus, "concept_a": {},
                            "concept_b": {}, "similarities": []},
            "citation_chunk_ids": [],
            "provider": "mock", "model_name": "mock",
            "fallback_used": False, "fallback_reason": "",
            "audit_run_id": 1,
        }

    monkeypatch.setattr(
        "app.services.concept_compare_service.generate_compare", fake_generate
    )
    get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id, user_focus="concept"
    )
    get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id, user_focus="exam"
    )
    assert call_count["n"] == 2, "不同 user_focus 必须生成不同报告"


def test_compare_cache_invalidates_when_evidence_changes(db_session, monkeypatch):
    """证据变化后不应复用旧的无证据 fallback 报告。"""
    import json as _json
    from app.models import MaterialChunk
    from app.services.concept_compare_service import get_or_create_compare_report

    user, n1, n2 = _setup_two_nodes(db_session)
    call_count = {"n": 0}

    def fake_generate(db, uid, concept_a, concept_b, evidence_chunks=None,
                      user_config=None, user_focus="concept"):
        call_count["n"] += 1
        return {
            "report_json": {"concept_a": {}, "concept_b": {}, "similarities": []},
            "citation_chunk_ids": [c["chunk_id"] for c in (evidence_chunks or [])],
            "provider": "mock", "model_name": "mock",
            "fallback_used": False, "fallback_reason": "",
            "audit_run_id": 1,
        }

    monkeypatch.setattr(
        "app.services.concept_compare_service.generate_compare", fake_generate
    )
    # 第一次：无证据
    get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id, user_focus="concept"
    )
    # 给节点加证据
    ch = MaterialChunk(
        material_id=1, course_id=n1.course_id, chunk_index=0,
        title="新证据", page_no=1, text="新证据文本",
    )
    db_session.add(ch)
    db_session.commit()
    n1.source_chunk_ids = _json.dumps([ch.id])
    db_session.commit()
    # 第二次：有证据，不应复用旧报告
    get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id, user_focus="concept"
    )
    assert call_count["n"] == 2, "证据变化后必须重新生成报告"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py::test_compare_cache_separates_user_focus app/tests/test_concept_compare_agent.py::test_compare_cache_invalidates_when_evidence_changes -v`
Expected: FAIL — 两次都命中同一缓存，`call_count["n"] == 1`

- [ ] **Step 3: 实现 — 模型加列 + service 缓存过滤**

3a. 修改 `backend/app/models/concept_graph.py` 的 `ConceptCompareReport`，在 `audit_run_id` 列之前追加两列：
```python
    user_focus = Column(String(50), default="concept")
    evidence_hash = Column(String(64), default="")
```

3b. 修改 `backend/app/services/concept_compare_service.py`：

在文件顶部 `import json` 之后追加：
```python
import hashlib
```

在 `get_or_create_compare_report` 中，将缓存查找块（从 `# Cache lookup` 到 `return _report_to_dict(cached)`）替换为：
```python
    # Collect evidence chunks from nodes and edge BEFORE cache lookup so
    # we can hash them and include the hash in the cache key.
    chunk_ids = _collect_chunk_ids(n1, n2, edge)
    evidence_hash = hashlib.sha1(
        json.dumps(sorted(chunk_ids)).encode("utf-8")
    ).hexdigest()[:16]

    # Cache lookup: same user + same node pair (either order) + same
    # user_focus + same evidence_hash. Different focus or evidence must
    # NOT reuse an old report.
    cached = (
        db.query(ConceptCompareReport)
        .filter_by(
            user_id=user_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            user_focus=user_focus,
            evidence_hash=evidence_hash,
        )
        .first()
    )
    if cached is None:
        cached = (
            db.query(ConceptCompareReport)
            .filter_by(
                user_id=user_id,
                source_node_id=target_node_id,
                target_node_id=source_node_id,
                user_focus=user_focus,
                evidence_hash=evidence_hash,
            )
            .first()
        )
    if cached is not None:
        return _report_to_dict(cached)
```

并删除原来下方重复的 `chunk_ids = _collect_chunk_ids(n1, n2, edge)` 与 `evidence_chunks = _load_evidence_chunks(db, user_id, chunk_ids)` 中靠前的那次收集（保留 evidence_chunks 加载）：
```python
    evidence_chunks = _load_evidence_chunks(db, user_id, chunk_ids)
```

在创建 `ConceptCompareReport(...)` 时追加两个字段：
```python
    report = ConceptCompareReport(
        user_id=user_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_id=edge_id,
        report_json=json.dumps(
            result["report_json"], ensure_ascii=False
        ),
        citation_chunk_ids=json.dumps(result["citation_chunk_ids"]),
        prompt_version="v1",
        provider=result["provider"],
        model_name=result["model_name"],
        user_focus=user_focus,
        evidence_hash=evidence_hash,
        audit_run_id=result["audit_run_id"],
    )
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 运行全部后端测试确认无回归**

Run: `cd backend && python -m pytest app/tests/ -q`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/models/concept_graph.py backend/app/services/concept_compare_service.py backend/app/tests/test_concept_compare_agent.py
git commit -m "fix(compare): cache by user_focus and evidence_hash to avoid stale reports"
```

---

## Task 5: mismatched edge 返回 BAD_REQUEST (P1)

**Files:**
- Modify: `backend/app/services/concept_compare_service.py`
- Modify: `backend/app/api/v1/endpoints/concept_graph.py`
- Test: `backend/app/tests/test_concept_compare_agent.py`
- Test: `backend/app/tests/test_concept_graph_api.py`

- [ ] **Step 1: 写失败测试 — service 抛 BusinessException**

在 `test_concept_compare_agent.py` 末尾追加：
```python
def test_compare_mismatched_edge_raises_business_exception(db_session):
    """edge 与节点对不匹配时 service 抛 BusinessException（400）。"""
    from app.core.exceptions import BusinessException
    from app.models import ConceptEdge

    user, n1, n2 = _setup_two_nodes(db_session)
    c3 = Course(name="网络", user_id=user.id)
    db_session.add(c3)
    db_session.commit()
    n3 = ConceptNode(
        user_id=user.id, course_id=c3.id, title="TCP",
        normalized_title="tcp", summary="传输控制协议",
    )
    db_session.add(n3)
    db_session.commit()
    mismatch_edge = ConceptEdge(
        user_id=user.id, source_node_id=n2.id, target_node_id=n3.id,
        relation_type="similar_to", confidence=0.5,
        evidence_chunk_ids="[]", status="candidate",
    )
    db_session.add(mismatch_edge)
    db_session.commit()
    try:
        get_or_create_compare_report(
            db_session, user.id, n1.id, n2.id, edge_id=mismatch_edge.id
        )
        assert False, "应抛 BusinessException"
    except BusinessException as exc:
        assert exc.status_code == 400
```

把 `test_compare_rejects_mismatched_edge_id` 旧测试改为期望 `BusinessException`：将该测试函数体中
```python
    result = get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id, edge_id=mismatch_edge.id
    )
    assert result is None
```
替换为：
```python
    try:
        get_or_create_compare_report(
            db_session, user.id, n1.id, n2.id, edge_id=mismatch_edge.id
        )
        assert False, "应抛 BusinessException"
    except BusinessException:
        pass
```
并在该文件 import 区追加（若尚无）：
```python
from app.core.exceptions import BusinessException
```

- [ ] **Step 2: 写 API 失败测试 — 400 统一错误格式**

在 `test_concept_graph_api.py` 末尾追加：
```python
def test_compare_mismatched_edge_returns_400(client):
    """edge 与节点对不匹配返回 400 统一错误格式。"""
    headers = auth_headers(client, username="alice")
    os_id = create_course(client, headers, name="操作系统")
    db_id = create_course(client, headers, name="数据库")
    _seed_kps(
        client,
        [
            {"course_id": os_id, "title": "死锁", "summary": "资源循环等待"},
            {"course_id": db_id, "title": "死锁", "summary": "事务锁冲突"},
            {"course_id": db_id, "title": "事务", "summary": "数据库事务"},
        ],
    )
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    graph = client.get("/api/v1/concept-graph", headers=headers).json()
    # 找一条连接 (n2, n3) 的边，请求 (n1, n2) 的 compare
    nodes = graph["nodes"]
    assert len(nodes) >= 2
    n1 = nodes[0]
    # 找一条不连接 n1 的边
    mismatch_edge = None
    for e in graph["edges"]:
        if e["source_node_id"] != n1["id"] and e["target_node_id"] != n1["id"]:
            mismatch_edge = e
            break
    if mismatch_edge is None:
        # 没有现成的 mismatch 边，构造一个：任意两条边互换
        assert len(graph["edges"]) >= 1
        mismatch_edge = graph["edges"][0]
        # 用一个不属于该边的节点 id
        other_node = next(n for n in nodes if n["id"] != mismatch_edge["source_node_id"] and n["id"] != mismatch_edge["target_node_id"])
        resp = client.post(
            "/api/v1/concept-graph/compare",
            headers=headers,
            json={
                "source_node_id": other_node["id"],
                "target_node_id": mismatch_edge["source_node_id"],
                "edge_id": mismatch_edge["id"],
            },
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "code" in body
        assert "message" in body
        assert "detail" not in body
        return
    resp = client.post(
        "/api/v1/concept-graph/compare",
        headers=headers,
        json={
            "source_node_id": n1["id"],
            "target_node_id": mismatch_edge["source_node_id"],
            "edge_id": mismatch_edge["id"],
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "code" in body
    assert "message" in body
    assert "detail" not in body
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py::test_compare_mismatched_edge_raises_business_exception app/tests/test_concept_graph_api.py::test_compare_mismatched_edge_returns_400 -v`
Expected: FAIL — service 仍返回 None（404），未抛 BusinessException

- [ ] **Step 4: 实现 — service 抛异常 + endpoint 放行**

4a. 修改 `backend/app/services/concept_compare_service.py`：

在 import 区追加：
```python
from app.core.exceptions import BusinessException
```

将 edge 一致性校验块：
```python
        if edge_pair != req_pair:
            return None
```
替换为：
```python
        if edge_pair != req_pair:
            raise BusinessException(
                message="edge 与请求的节点对不匹配"
            )
```

4b. `backend/app/api/v1/endpoints/concept_graph.py` 无需改动——`BusinessException` 继承 `AppException`，会被全局 handler 转成 400 `{code, message}`，而 `result is None` 仍走 `NotFoundException`。确认 endpoint 的 compare 函数仍是：
```python
    if result is None:
        raise NotFoundException(message="节点不存在")
```
（保持不变）

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd backend && python -m pytest app/tests/test_concept_compare_agent.py app/tests/test_concept_graph_api.py -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/concept_compare_service.py backend/app/tests/test_concept_compare_agent.py backend/app/tests/test_concept_graph_api.py
git commit -m "fix(compare): mismatched edge returns 400 instead of 404"
```

---

## Task 6: 前端 compare drawer 增加 user_focus 选择器 (P1)

**Files:**
- Modify: `frontend/src/api/conceptGraph.ts`
- Modify: `frontend/src/views/KnowledgeGraphView.vue`

- [ ] **Step 1: 修改 API 层 — compareNodes 接收 user_focus**

将 `frontend/src/api/conceptGraph.ts` 的 `compareNodes` 改为：
```typescript
export function compareNodes(
  sourceNodeId: number,
  targetNodeId: number,
  edgeId?: number,
  userFocus: string = 'concept',
): AxiosPromise<CompareReport> {
  return request.post('/concept-graph/compare', {
    source_node_id: sourceNodeId,
    target_node_id: targetNodeId,
    edge_id: edgeId ?? null,
    user_focus: userFocus,
  })
}
```

- [ ] **Step 2: 修改视图层 — drawer 增加 user_focus 选择器**

2a. 在 `KnowledgeGraphView.vue` 的 `<script setup>` 中，`const compareLoading = ref(false)` 之后追加：
```typescript
const compareUserFocus = ref<'concept' | 'exam' | 'confusion'>('concept')

const userFocusOptions: { label: string; value: string }[] = [
  { label: '概念理解', value: 'concept' },
  { label: '考试复习', value: 'exam' },
  { label: '易混点对比', value: 'confusion' },
]
```

2b. 修改 `handleCompare` 函数，把 `compareUserFocus.value` 传给 `compareNodes`：
```typescript
async function handleCompare() {
  if (!selectedEdge.value) return
  compareLoading.value = true
  compareDrawerVisible.value = true
  compareReport.value = null
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
  } finally {
    compareLoading.value = false
  }
}
```

2c. 在 compare drawer 的 `<div v-loading="compareLoading">` 之后、`<div v-if="compareReport" class="compare-report">` 之前，插入 user_focus 选择器：
```html
      <div v-loading="compareLoading">
        <div class="compare-focus-bar">
          <span class="focus-label">关注点</span>
          <el-radio-group v-model="compareUserFocus" size="small">
            <el-radio-button
              v-for="opt in userFocusOptions"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </el-radio-button>
          </el-radio-group>
          <el-button
            size="small"
            type="primary"
            :loading="compareLoading"
            @click="handleCompare"
          >
            重新生成
          </el-button>
        </div>
        <div v-if="compareReport" class="compare-report">
```
（注意：删掉原来紧接的 `<div v-if="compareReport" class="compare-report">` 开标签，避免重复）

2d. 在 `<style scoped>` 末尾 `</style>` 之前追加：
```css
.compare-focus-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 6px;
}

.focus-label {
  font-size: 13px;
  color: #606266;
  font-weight: 600;
}
```

- [ ] **Step 3: 运行前端构建**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api/conceptGraph.ts frontend/src/views/KnowledgeGraphView.vue
git commit -m "feat(graph): add user_focus selector to compare drawer"
```

---

## Task 7: 验收脚本第 12 节静态检查 (P3)

**Files:**
- Modify: `scripts/verify_phase2_engineering.ps1`
- Modify: `scripts/verify_phase2_engineering.sh`

- [ ] **Step 1: 在 ps1 第 11 节后追加第 12 节**

在 `scripts/verify_phase2_engineering.ps1` 的 `Write-Host ''`（最终判定前）之前追加：
```powershell
# 12. P3: v2 audit remediation checks
Write-Step 'Concept compare mock builder check'
$llmPy = Get-Content "$root\backend\app\agents\llm.py" -Raw
if ($llmPy -match '"concept_compare": _mock_concept_compare') {
  Write-Ok 'llm.py registers concept_compare mock builder'
} else {
  Write-Bad 'llm.py missing concept_compare mock builder'
}

Write-Step 'Concept compare no hardcoded empty evidence check'
$kgCompareContent2 = Get-Content "$root\backend\app\services\concept_compare_service.py" -Raw
if ($kgCompareContent2 -match 'evidence_chunks=\[\]') {
  Write-Bad 'concept_compare_service hardcodes evidence_chunks=[]'
} else {
  Write-Ok 'concept_compare_service has no hardcoded empty evidence'
}

Write-Step 'Concept compare prompt user_focus check'
$kgPrompt = Get-Content "$root\backend\app\agents\prompts\concept_compare_v1.md" -Raw
if ($kgPrompt -match 'user_focus') {
  Write-Ok 'concept_compare prompt includes user_focus'
} else {
  Write-Bad 'concept_compare prompt missing user_focus'
}

Write-Step 'Concept compare cache granularity check'
if ($kgCompareContent2 -match 'evidence_hash' -and $kgCompareContent2 -match 'user_focus') {
  Write-Ok 'concept_compare_service cache keys on user_focus and evidence_hash'
} else {
  Write-Bad 'concept_compare_service cache missing user_focus/evidence_hash'
}
```

- [ ] **Step 2: 在 sh 追加等价第 12 节**

在 `scripts/verify_phase2_engineering.sh` 的 `echo ""`（最终判定前）之前追加：
```bash
# 12. P3: v2 audit remediation checks
step "Concept compare mock builder check"
llm_py="$root/backend/app/agents/llm.py"
if grep -q '"concept_compare": _mock_concept_compare' "$llm_py"; then
  ok "llm.py registers concept_compare mock builder"
else
  bad "llm.py missing concept_compare mock builder"
fi

step "Concept compare no hardcoded empty evidence check"
if grep -q 'evidence_chunks=\[\]' "$kg_compare_service"; then
  bad "concept_compare_service hardcodes evidence_chunks=[]"
else
  ok "concept_compare_service has no hardcoded empty evidence"
fi

step "Concept compare prompt user_focus check"
kg_prompt="$root/backend/app/agents/prompts/concept_compare_v1.md"
if grep -q 'user_focus' "$kg_prompt"; then
  ok "concept_compare prompt includes user_focus"
else
  bad "concept_compare prompt missing user_focus"
fi

step "Concept compare cache granularity check"
if grep -q 'evidence_hash' "$kg_compare_service" && grep -q 'user_focus' "$kg_compare_service"; then
  ok "concept_compare_service cache keys on user_focus and evidence_hash"
else
  bad "concept_compare_service cache missing user_focus/evidence_hash"
fi

echo ""
```

- [ ] **Step 3: 运行验收脚本**

Run: `pwsh -NoProfile -File ./scripts/verify_phase2_engineering.ps1`
Expected: ACCEPTANCE PASSED（含新增 4 项检查全部 OK）

- [ ] **Step 4: 提交**

```bash
git add scripts/verify_phase2_engineering.ps1 scripts/verify_phase2_engineering.sh
git commit -m "chore(graph): add v2 audit remediation acceptance checks"
```

---

## Task 8: 全量验证 + 推送 + 触发 CI + 验证 artifacts (P3)

**Files:** 无（仅命令）

- [ ] **Step 1: 运行全部后端测试**

Run: `cd backend && python -m pytest app/tests/ -q`
Expected: 全部 PASS

- [ ] **Step 2: 运行前端构建**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 3: 运行验收脚本**

Run: `pwsh -NoProfile -File ./scripts/verify_phase2_engineering.ps1`
Expected: ACCEPTANCE PASSED

- [ ] **Step 4: 推送到 GitHub**

Run: `git push origin main`
Expected: 推送成功

- [ ] **Step 5: 手动触发 workflow_dispatch**

Run: `gh workflow run ci.yml --ref main`
Expected: 命令成功，无输出

- [ ] **Step 6: 等待 CI 完成并验证 artifacts**

Run: `Start-Sleep -Seconds 30; gh run list --limit 1 --json databaseId,status,conclusion -q '.[0]'`，然后轮询直到 `status=completed`。再运行 `gh run view <id> --json jobs` 确认三个 job 都 success。最后 `gh api repos/dddd2024/course-learning-agent/actions/runs/<id>/artifacts` 确认存在 `backend-test-result`、`frontend-build-result`、`acceptance-result` 三个 artifacts。
Expected: 三个 job success + 三个 artifacts 存在

---

## Self-Review

**1. Spec coverage:**
- P0 mock citation → Task 1 ✓
- P0 compare 加载 MaterialChunk → 已在 06bc8b8 完成（_load_evidence_chunks），本轮 Task 1 验证 mock 链路 ✓
- P1 user_config 透传 → 已在 06bc8b8 完成，本轮不动 ✓
- P1 edge_id 校验 → Task 5（区分 404/400）✓
- P1 缓存粒度 → Task 4 ✓
- P1 user_focus 进 prompt → Task 2 + Task 3 ✓
- P2 中文 n-gram → 已在 1388e91 完成 ✓
- P3 验收脚本 → Task 7 ✓
- P3 CI artifacts → Task 8 ✓
- 前端 user_focus → Task 6 ✓

**2. Placeholder scan:** 无 TBD/TODO，每个步骤含完整代码。

**3. Type consistency:**
- `generate_compare(..., user_focus="concept")` 在 Task 2 定义，Task 3 service 传递，Task 4 缓存使用 — 一致 ✓
- `_mock_concept_compare(prompt)` 在 Task 1 定义，`_mock_response(agent_type, prompt)` 调用 `builder(prompt)` — 一致 ✓
- `BusinessException` 在 Task 5 service 抛出，全局 handler 处理 — 一致 ✓
- `user_focus` / `evidence_hash` 列在 Task 4 模型定义，service 写入与查询使用 — 一致 ✓
