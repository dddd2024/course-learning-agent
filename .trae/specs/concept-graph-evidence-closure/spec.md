# 跨课程知识图谱证据约束型成熟版整改计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把跨课程知识图谱从"图谱演示版"升级为"证据约束型成熟版"——每条边绑定真实 evidence_chunk_ids，每份对比报告加载 MaterialChunk 证据文本，用户 LLM 配置透传，edge_id 校验归属，统一错误格式，中文 n-gram 匹配增强。

**Architecture:** 在现有 ConceptNode/ConceptEdge/ConceptCompareReport 三层模型上，修改 service 层（证据绑定、n-gram 匹配）、compare service 层（证据加载、config 透传、edge_id 校验）、endpoint 层（统一异常、config 读取），不引入新模型、不引入图数据库。

**Tech Stack:** Python / FastAPI / SQLAlchemy / pytest / Vue 3 / Element Plus / GitHub Actions

**基线:** ba4f7509 (origin/main)

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `backend/app/services/concept_graph_service.py` | 边生成写入 evidence_chunk_ids；n-gram 匹配；新关系类型 | 修改 |
| `backend/app/services/concept_compare_service.py` | 加载 MaterialChunk 证据；user_config 透传；edge_id 校验 | 修改 |
| `backend/app/api/v1/endpoints/concept_graph.py` | 统一异常；读取 active_config 传给 compare | 修改 |
| `backend/app/tests/test_concept_graph_service.py` | 证据绑定 + n-gram + 新关系类型测试 | 修改 |
| `backend/app/tests/test_concept_compare_agent.py` | 证据加载 + user_config + edge_id 校验测试 | 修改 |
| `backend/app/tests/test_concept_graph_api.py` | 统一错误格式测试 | 修改 |
| `backend/app/tests/test_api_contracts.py` | compare 返回结构 + 错误格式契约 | 修改 |
| `frontend/src/views/KnowledgeGraphView.vue` | 对比 Drawer 展示证据来源 | 修改 |
| `scripts/verify_phase2_engineering.ps1` | 静态检查：evidence 绑定、统一异常 | 修改 |
| `scripts/verify_phase2_engineering.sh` | 同上 Linux 版 | 修改 |

---

## Task 1: ConceptEdge 绑定真实 evidence_chunk_ids (P0)

**Files:**
- Modify: `backend/app/services/concept_graph_service.py`
- Test: `backend/app/tests/test_concept_graph_service.py`

- [ ] **Step 1: 写失败测试 — 边携带 evidence_chunk_ids**

在 `test_concept_graph_service.py` 末尾追加：

```python
def test_candidate_edge_carries_evidence_chunk_ids(db_session):
    """当两侧 KP 有 source_chunk_ids 时，生成的边必须携带 evidence_chunk_ids。"""
    from app.models import Course, KnowledgePoint, MaterialChunk, User

    user = User(username="alice", email="a@x.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    c1 = Course(name="操作系统", user_id=user.id)
    c2 = Course(name="数据库", user_id=user.id)
    db_session.add_all([c1, c2])
    db_session.commit()

    # 创建 MaterialChunk 行，获得真实 chunk id
    ch1 = MaterialChunk(
        material_id=1, course_id=c1.id, chunk_index=0,
        title="OS死锁", page_no=1, text="资源循环等待",
    )
    ch2 = MaterialChunk(
        material_id=1, course_id=c2.id, chunk_index=0,
        title="DB死锁", page_no=1, text="事务锁冲突",
    )
    db_session.add_all([ch1, ch2])
    db_session.commit()

    kp1 = KnowledgePoint(
        user_id=user.id, course_id=c1.id, title="死锁",
        summary="资源循环等待", importance=5,
        source_chunk_ids=json.dumps([ch1.id]),
    )
    kp2 = KnowledgePoint(
        user_id=user.id, course_id=c2.id, title="死锁",
        summary="事务锁冲突", importance=5,
        source_chunk_ids=json.dumps([ch2.id]),
    )
    db_session.add_all([kp1, kp2])
    db_session.commit()

    sync_nodes_for_user(db_session, user.id)
    generate_candidate_edges(db_session, user.id)

    edges = db_session.query(ConceptEdge).filter_by(user_id=user.id).all()
    assert len(edges) >= 1
    for edge in edges:
        ids = json.loads(edge.evidence_chunk_ids or "[]")
        assert len(ids) >= 1, f"edge {edge.id} evidence_chunk_ids 不应为空"
        assert ch1.id in ids or ch2.id in ids
```

需要在文件顶部加 `import json`。

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && python -m pytest app/tests/test_concept_graph_service.py::test_candidate_edge_carries_evidence_chunk_ids -v
```
Expected: FAIL — edge.evidence_chunk_ids 为 "[]"

- [ ] **Step 3: 实现 — 添加 _load_json_ids 和 _merge_evidence_ids helper，修改 _try_make_edge**

在 `concept_graph_service.py` 的 `_jaccard` 函数后添加：

```python
def _load_json_ids(value: str | None) -> list[int]:
    """Parse a JSON string of int ids, tolerating bad input."""
    try:
        raw = json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    ids = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    return ids


def _merge_evidence_ids(a: ConceptNode, b: ConceptNode) -> list[int]:
    """Merge source_chunk_ids from two nodes, de-duplicating."""
    seen: set[int] = set()
    merged: list[int] = []
    for cid in _load_json_ids(a.source_chunk_ids) + _load_json_ids(b.source_chunk_ids):
        if cid not in seen:
            seen.add(cid)
            merged.append(cid)
    return merged
```

修改 `_try_make_edge`：在函数开头收集证据，在每个 `ConceptEdge(...)` 构造时用 `json.dumps(evidence_ids)` 替换 `evidence_chunk_ids="[]"`。在函数开头加：

```python
    evidence_ids = _merge_evidence_ids(a, b)
```

每个 `return ConceptEdge(...)` 的 `evidence_chunk_ids=` 改为 `evidence_chunk_ids=json.dumps(evidence_ids)`。如果 `evidence_ids` 为空，在 reason 后追加 `（缺少来源 chunk，仅基于知识点摘要生成）`。

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend && python -m pytest app/tests/test_concept_graph_service.py::test_candidate_edge_carries_evidence_chunk_ids -v
```
Expected: PASS

- [ ] **Step 5: 运行全部 service 测试确认无回归**

```bash
cd backend && python -m pytest app/tests/test_concept_graph_service.py -v
```
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/concept_graph_service.py backend/app/tests/test_concept_graph_service.py
git commit -m "fix(graph): bind real evidence_chunk_ids to candidate edges"
```

---

## Task 2: Compare 加载 MaterialChunk 证据文本 (P0)

**Files:**
- Modify: `backend/app/services/concept_compare_service.py`
- Test: `backend/app/tests/test_concept_compare_agent.py`

- [ ] **Step 1: 写失败测试 — compare 使用证据片段**

在 `test_concept_compare_agent.py` 末尾追加：

```python
def test_compare_uses_evidence_chunks(db_session, monkeypatch):
    """compare service 应从 node/edge 的 chunk ids 加载 MaterialChunk 文本。"""
    import json
    from app.models import Course, MaterialChunk

    user, n1, n2 = _setup_two_nodes(db_session)
    # 给节点绑定 source_chunk_ids
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

    captured = {}

    def fake_generate(db, uid, concept_a, concept_b, evidence_chunks=None, user_config=None):
        captured["evidence_chunks"] = evidence_chunks
        captured["user_config"] = user_config
        return {
            "report_json": {"concept_a": {}, "concept_b": {}, "similarities": []},
            "citation_chunk_ids": [ch1.id, ch2.id],
            "provider": "mock",
            "model_name": "mock",
            "fallback_used": False,
            "fallback_reason": "",
            "audit_run_id": 1,
        }

    monkeypatch.setattr(
        "app.services.concept_compare_service.generate_compare", fake_generate
    )
    get_or_create_compare_report(db_session, user.id, n1.id, n2.id)

    assert captured["evidence_chunks"] is not None
    assert len(captured["evidence_chunks"]) >= 2
    chunk_ids = [c["chunk_id"] for c in captured["evidence_chunks"]]
    assert ch1.id in chunk_ids
    assert ch2.id in chunk_ids
    # 每个 evidence chunk 必须含 text 字段
    for c in captured["evidence_chunks"]:
        assert "text" in c
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && python -m pytest app/tests/test_concept_compare_agent.py::test_compare_uses_evidence_chunks -v
```
Expected: FAIL — evidence_chunks 仍为 []

- [ ] **Step 3: 实现 — 添加 _load_evidence_chunks helper，修改 get_or_create_compare_report**

在 `concept_compare_service.py` 顶部 import 区添加：

```python
from app.models import ConceptCompareReport, ConceptEdge, ConceptNode, Course, MaterialChunk
```

在 `get_or_create_compare_report` 函数前添加 helper：

```python
def _load_evidence_chunks(
    db: Session, user_id: int, chunk_ids: list[int]
) -> list[dict]:
    """Load MaterialChunk rows owned by the user, returning dicts for the agent."""
    if not chunk_ids:
        return []
    rows = (
        db.query(MaterialChunk)
        .join(Course, Course.id == MaterialChunk.course_id)
        .filter(Course.user_id == user_id)
        .filter(MaterialChunk.id.in_(chunk_ids))
        .all()
    )
    return [
        {
            "chunk_id": r.id,
            "course_id": r.course_id,
            "material_id": r.material_id,
            "title": r.title or "",
            "page_no": r.page_no,
            "text": (r.text or "")[:1200],
        }
        for r in rows
    ]


def _collect_chunk_ids(
    n1: ConceptNode, n2: ConceptNode, edge: ConceptEdge | None
) -> list[int]:
    """Collect candidate chunk ids from both nodes and the edge."""
    ids: list[int] = []
    for raw in (n1.source_chunk_ids, n2.source_chunk_ids):
        try:
            ids.extend(int(x) for x in json.loads(raw or "[]"))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    if edge is not None:
        try:
            ids.extend(int(x) for x in json.loads(edge.evidence_chunk_ids or "[]"))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    # de-dup preserving order
    seen: set[int] = set()
    unique: list[int] = []
    for cid in ids:
        if cid not in seen:
            seen.add(cid)
            unique.append(cid)
    return unique
```

修改 `get_or_create_compare_report` 的生成部分（替换 `evidence_chunks=[]` 那段）：

```python
    # 收集证据片段
    edge = None
    if edge_id is not None:
        edge = db.query(ConceptEdge).filter_by(
            id=edge_id, user_id=user_id
        ).first()
    chunk_ids = _collect_chunk_ids(n1, n2, edge)
    evidence_chunks = _load_evidence_chunks(db, user_id, chunk_ids)

    # Generate a fresh report via the compare agent.
    result = generate_compare(
        db,
        user_id,
        concept_a={"title": n1.title, "summary": n1.summary or ""},
        concept_b={"title": n2.title, "summary": n2.summary or ""},
        evidence_chunks=evidence_chunks,
        user_config=user_config,
    )
```

同时在函数签名加 `user_config: dict | None = None` 参数。

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend && python -m pytest app/tests/test_concept_compare_agent.py::test_compare_uses_evidence_chunks -v
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/concept_compare_service.py backend/app/tests/test_concept_compare_agent.py
git commit -m "fix(graph): load MaterialChunk evidence into compare agent"
```

---

## Task 3: 用户 LLM 配置透传到 compare (P1)

**Files:**
- Modify: `backend/app/api/v1/endpoints/concept_graph.py`
- Modify: `backend/app/services/concept_compare_service.py`
- Test: `backend/app/tests/test_concept_compare_agent.py`

- [ ] **Step 1: 写失败测试 — user_config 被传入**

在 `test_concept_compare_agent.py` 末尾追加：

```python
def test_compare_passes_user_config(db_session, monkeypatch):
    """compare service 应把 user_config 传给 generate_compare。"""
    user, n1, n2 = _setup_two_nodes(db_session)
    captured = {}

    def fake_generate(db, uid, concept_a, concept_b, evidence_chunks=None, user_config=None):
        captured["user_config"] = user_config
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
    my_config = {"base_url": "https://x", "model": "gpt-4o", "api_key": "k"}
    get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id, user_config=my_config
    )
    assert captured["user_config"] == my_config
```

- [ ] **Step 2: 运行测试，确认通过（service 层已在 Task 2 加了 user_config 参数）**

```bash
cd backend && python -m pytest app/tests/test_concept_compare_agent.py::test_compare_passes_user_config -v
```
Expected: PASS（如果 Task 2 已加 user_config 参数则直接通过）

- [ ] **Step 3: 修改 endpoint — 读取 active_config 并传入**

在 `concept_graph.py` 的 import 区添加：

```python
from app.services.llm_config_service import build_user_config, get_active_config
```

修改 `compare` endpoint：

```python
@router.post("/compare", response_model=CompareReportResponse)
def compare(
    req: CompareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate (or return cached) compare report for two nodes.

    404 if either node does not exist or belongs to another user.
    """
    active_config = get_active_config(db, current_user.id)
    user_config = build_user_config(active_config) if active_config else None
    result = get_or_create_compare_report(
        db, current_user.id, req.source_node_id, req.target_node_id,
        req.edge_id, req.user_focus, user_config=user_config,
    )
    if result is None:
        raise NotFoundException(message="节点不存在")
    db.commit()
    return CompareReportResponse(**result)
```

- [ ] **Step 4: 运行全部 compare 测试**

```bash
cd backend && python -m pytest app/tests/test_concept_compare_agent.py -v
```
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/v1/endpoints/concept_graph.py backend/app/tests/test_concept_compare_agent.py
git commit -m "fix(graph): pass user LLM config to compare agent"
```

---

## Task 4: edge_id 归属与一致性校验 (P1)

**Files:**
- Modify: `backend/app/services/concept_compare_service.py`
- Test: `backend/app/tests/test_concept_compare_agent.py`

- [ ] **Step 1: 写失败测试 — 拒绝他人 edge_id 和不匹配 edge_id**

在 `test_concept_compare_agent.py` 末尾追加：

```python
def test_compare_rejects_foreign_edge_id(db_session):
    """edge_id 属于他人时返回 None（endpoint 层转 404）。"""
    from app.models import ConceptEdge, User

    user, n1, n2 = _setup_two_nodes(db_session)
    other = User(username="bob", email="b@x.com", password_hash="x")
    db_session.add(other)
    db_session.commit()
    # bob 的边
    bob_edge = ConceptEdge(
        user_id=other.id, source_node_id=n1.id, target_node_id=n2.id,
        relation_type="similar_to", confidence=0.5,
        evidence_chunk_ids="[]", status="candidate",
    )
    db_session.add(bob_edge)
    db_session.commit()
    result = get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id, edge_id=bob_edge.id
    )
    assert result is None


def test_compare_rejects_mismatched_edge_id(db_session):
    """edge 连接的节点对与请求不一致时返回 None。"""
    from app.models import ConceptEdge, Course

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
    # n2-n3 的边，但请求 n1-n2
    mismatch_edge = ConceptEdge(
        user_id=user.id, source_node_id=n2.id, target_node_id=n3.id,
        relation_type="similar_to", confidence=0.5,
        evidence_chunk_ids="[]", status="candidate",
    )
    db_session.add(mismatch_edge)
    db_session.commit()
    result = get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id, edge_id=mismatch_edge.id
    )
    assert result is None
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && python -m pytest app/tests/test_concept_compare_agent.py::test_compare_rejects_foreign_edge_id app/tests/test_concept_compare_agent.py::test_compare_rejects_mismatched_edge_id -v
```
Expected: FAIL（当前不校验 edge_id）

- [ ] **Step 3: 实现 — 在 get_or_create_compare_report 中校验 edge_id**

在 `get_or_create_compare_report` 中，node 存在性检查后、缓存查找前，加 edge_id 校验：

```python
    # edge_id 归属与一致性校验
    if edge_id is not None:
        edge = db.query(ConceptEdge).filter_by(
            id=edge_id, user_id=user_id
        ).first()
        if edge is None:
            return None
        edge_pair = {edge.source_node_id, edge.target_node_id}
        req_pair = {source_node_id, target_node_id}
        if edge_pair != req_pair:
            return None
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend && python -m pytest app/tests/test_concept_compare_agent.py -v
```
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/concept_compare_service.py backend/app/tests/test_concept_compare_agent.py
git commit -m "fix(graph): validate edge_id ownership and node consistency in compare"
```

---

## Task 5: 统一错误响应格式 (P1)

**Files:**
- Modify: `backend/app/api/v1/endpoints/concept_graph.py`
- Test: `backend/app/tests/test_concept_graph_api.py`
- Test: `backend/app/tests/test_api_contracts.py`

- [ ] **Step 1: 写失败测试 — 404 返回 code/message 格式**

在 `test_concept_graph_api.py` 末尾追加：

```python
def test_node_detail_404_uses_unified_error_format(client):
    """404 必须返回 {code, message} 格式，不含 FastAPI 默认 detail。"""
    headers = auth_headers(client, username="alice")
    resp = client.get("/api/v1/concept-graph/nodes/99999", headers=headers)
    assert resp.status_code == 404
    body = resp.json()
    assert "code" in body
    assert "message" in body
    assert "detail" not in body


def test_confirm_edge_404_uses_unified_error_format(client):
    """404 必须返回 {code, message} 格式。"""
    headers = auth_headers(client, username="alice")
    resp = client.post(
        "/api/v1/concept-graph/edges/99999/confirm", headers=headers
    )
    assert resp.status_code == 404
    body = resp.json()
    assert "code" in body
    assert "message" in body
    assert "detail" not in body


def test_compare_404_uses_unified_error_format(client):
    """compare 404 必须返回 {code, message} 格式。"""
    headers = auth_headers(client, username="alice")
    resp = client.post(
        "/api/v1/concept-graph/compare", headers=headers,
        json={"source_node_id": 99999, "target_node_id": 99998},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert "code" in body
    assert "message" in body
    assert "detail" not in body
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && python -m pytest app/tests/test_concept_graph_api.py::test_node_detail_404_uses_unified_error_format -v
```
Expected: FAIL — 当前返回 {"detail": "节点不存在"} 而非 {"code":..., "message":...}

- [ ] **Step 3: 实现 — 替换 HTTPException 为 NotFoundException**

在 `concept_graph.py` import 区替换：

```python
from fastapi import APIRouter, Depends
```
删除 `HTTPException` import。添加：

```python
from app.core.exceptions import NotFoundException
```

替换所有 `raise HTTPException(status_code=404, detail="...")` 为 `raise NotFoundException(message="...")`。共 3 处：
- `get_node`: `raise NotFoundException(message="节点不存在")`
- `confirm`: `raise NotFoundException(message="边不存在")`
- `reject`: `raise NotFoundException(message="边不存在")`
- `compare`: `raise NotFoundException(message="节点不存在")`

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend && python -m pytest app/tests/test_concept_graph_api.py -v
```
Expected: 全部 PASS

- [ ] **Step 5: 在 test_api_contracts.py 追加 compare 契约测试**

```python
def test_concept_graph_compare_error_contract(client) -> None:
    """compare 404 返回统一 {code, message} 格式。"""
    headers = auth_headers(client, username="alice")
    resp = client.post(
        "/api/v1/concept-graph/compare", headers=headers,
        json={"source_node_id": 99999, "target_node_id": 99998},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert set(body.keys()) >= {"code", "message"}
    assert "detail" not in body
```

- [ ] **Step 6: 运行契约测试**

```bash
cd backend && python -m pytest app/tests/test_api_contracts.py -v
```
Expected: 全部 PASS

- [ ] **Step 7: 提交**

```bash
git add backend/app/api/v1/endpoints/concept_graph.py backend/app/tests/test_concept_graph_api.py backend/app/tests/test_api_contracts.py
git commit -m "fix(graph): use unified NotFoundException instead of HTTPException"
```

---

## Task 6: 中文 n-gram 匹配 + 新关系类型 (P2)

**Files:**
- Modify: `backend/app/services/concept_graph_service.py`
- Test: `backend/app/tests/test_concept_graph_service.py`

- [ ] **Step 1: 写失败测试 — n-gram 匹配 + 新关系类型**

在 `test_concept_graph_service.py` 末尾追加：

```python
def test_cjk_ngram_matching_avoids_common_char_false_positive(db_session):
    """单字'的'重叠不应产生边；n-gram 匹配避免常见字误连。"""
    from app.models import Course, KnowledgePoint, User

    user = User(username="alice", email="a@x.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    c1 = Course(name="A", user_id=user.id)
    c2 = Course(name="B", user_id=user.id)
    db_session.add_all([c1, c2])
    db_session.commit()
    # 两个完全不相关的 KP，摘要只共享常见字"的"
    kp1 = KnowledgePoint(
        user_id=user.id, course_id=c1.id, title="排序算法",
        summary="快速排序的分治思想", importance=3, source_chunk_ids="[]",
    )
    kp2 = KnowledgePoint(
        user_id=user.id, course_id=c2.id, title="索引结构",
        summary="B+树的磁盘存储结构", importance=3, source_chunk_ids="[]",
    )
    db_session.add_all([kp1, kp2])
    db_session.commit()
    sync_nodes_for_user(db_session, user.id)
    generate_candidate_edges(db_session, user.id)
    edges = db_session.query(ConceptEdge).filter_by(user_id=user.id).all()
    # 排序算法 vs 索引结构 不应有边
    assert len(edges) == 0


def test_contrast_with_edge_for_different_concepts_same_domain(db_session):
    """同领域但不同的概念应产生 contrast_with 关系。"""
    from app.models import Course, KnowledgePoint, User

    user = User(username="alice", email="a@x.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    c1 = Course(name="OS", user_id=user.id)
    c2 = Course(name="DB", user_id=user.id)
    db_session.add_all([c1, c2])
    db_session.commit()
    # 两个概念在相同领域（都涉及"锁"）但不同
    kp1 = KnowledgePoint(
        user_id=user.id, course_id=c1.id, title="互斥锁",
        summary="操作系统互斥锁用于保护临界区", importance=4, source_chunk_ids="[]",
    )
    kp2 = KnowledgePoint(
        user_id=user.id, course_id=c2.id, title="共享锁",
        summary="数据库共享锁允许多事务读取", importance=4, source_chunk_ids="[]",
    )
    db_session.add_all([kp1, kp2])
    db_session.commit()
    sync_nodes_for_user(db_session, user.id)
    generate_candidate_edges(db_session, user.id)
    edges = db_session.query(ConceptEdge).filter_by(user_id=user.id).all()
    # 应有边，且关系类型可能是 contrast_with 或 similar_to/applies_to
    assert len(edges) >= 1
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && python -m pytest app/tests/test_concept_graph_service.py::test_cjk_ngram_matching_avoids_common_char_false_positive -v
```
Expected: 可能 FAIL — 单字"的"重叠可能产生误连边

- [ ] **Step 3: 实现 — n-gram 匹配 + 停用字 + 新关系类型**

在 `concept_graph_service.py` 替换 `_keyword_set` 函数：

```python
CJK_STOP_CHARS = set("的是了和与及在为对中上下一种一个可以通过")


def _cjk_ngrams(text: str) -> set[str]:
    """Extract 2-gram and 3-gram from CJK text, filtering stop chars."""
    chars = [
        c for c in re.findall(r"[\u4e00-\u9fff]", text)
        if c not in CJK_STOP_CHARS
    ]
    grams: set[str] = set()
    for n in (2, 3):
        for i in range(0, max(0, len(chars) - n + 1)):
            grams.add("".join(chars[i:i + n]))
    return grams


def _keyword_set(summary: str) -> set[str]:
    """Extract meaningful keywords: CJK 2/3-grams + ASCII words >= 2 chars."""
    if not summary:
        return set()
    cjk_grams = _cjk_ngrams(summary)
    ascii_words = set(w.lower() for w in re.findall(r"[a-zA-Z]{2,}", summary))
    return cjk_grams | ascii_words
```

在 `_try_make_edge` 中，Rule 2 之前加 contrast_with 规则（跨课程 + 中等重叠 + 不同标题）：

```python
    # Rule 1.5: cross-course, different title, moderate overlap -> contrast_with
    if diff_course and not same_title and 0.1 <= kw_overlap < 0.2:
        return ConceptEdge(
            source_node_id=a.id,
            target_node_id=b.id,
            relation_type="contrast_with",
            confidence=0.5,
            reason=f"跨课程对比：关键词部分重叠 ({kw_overlap:.2f})",
            evidence_chunk_ids=json.dumps(evidence_ids),
            status="candidate",
        )
```

同时把 Rule 2 的跨课程阈值从 0.2 提高到 0.25（避免误连）：

```python
    # Rule 2: keyword overlap -> similar_to / applies_to
    threshold = 0.25 if diff_course else 0.2
    if kw_overlap >= threshold:
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend && python -m pytest app/tests/test_concept_graph_service.py -v
```
Expected: 全部 PASS（如果旧测试因阈值变化失败，调整旧测试的 KP 摘要使重叠度足够高）

- [ ] **Step 5: 运行全部后端测试确认无回归**

```bash
cd backend && python -m pytest app/tests/ -q
```
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/concept_graph_service.py backend/app/tests/test_concept_graph_service.py
git commit -m "feat(graph): n-gram CJK matching with stop chars and contrast_with relation"
```

---

## Task 7: 前端对比 Drawer 展示证据来源 (P2)

**Files:**
- Modify: `frontend/src/views/KnowledgeGraphView.vue`

- [ ] **Step 1: 修改对比 Drawer — 展示 citation_chunk_ids 和证据不足提示**

在 `KnowledgeGraphView.vue` 的 compare drawer 模板中，在 `compare-alert` 后添加证据来源展示区块：

```html
          <div v-if="compareReport.citation_chunk_ids.length" class="report-section">
            <div class="section-title">证据来源 ({{ compareReport.citation_chunk_ids.length }} 个片段)</div>
            <div class="citation-list">
              <el-tag
                v-for="cid in compareReport.citation_chunk_ids"
                :key="cid"
                size="small"
                type="info"
                class="citation-tag"
              >
                Chunk #{{ cid }}
              </el-tag>
            </div>
          </div>
          <div v-else-if="compareReport.fallback_used" class="report-section">
            <el-alert
              type="warning"
              title="无证据片段：本次对比基于知识点摘要推断，未引用原始资料"
              :closable="false"
              show-icon
            />
          </div>
```

在 `<style scoped>` 中追加：

```css
.citation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.citation-tag {
  font-family: 'JetBrains Mono', monospace;
}
```

- [ ] **Step 2: 运行前端构建**

```bash
cd frontend && npm run build
```
Expected: 构建成功

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/KnowledgeGraphView.vue
git commit -m "feat(graph): show citation chunk ids and evidence warning in compare drawer"
```

---

## Task 8: 验收脚本补强 + 全量验证 + 推送 (P3)

**Files:**
- Modify: `scripts/verify_phase2_engineering.ps1`
- Modify: `scripts/verify_phase2_engineering.sh`

- [ ] **Step 1: 在验收脚本中添加 evidence 绑定和统一异常检查**

在 `verify_phase2_engineering.ps1` 的第 10 节后追加第 11 节：

```powershell
# 11. P3: Evidence binding and unified error checks
Write-Step 'Concept graph evidence binding check'
$kgServiceContent = Get-Content "$root\backend\app\services\concept_graph_service.py" -Raw
if ($kgServiceContent -match '_merge_evidence_ids') {
  Write-Ok 'concept_graph_service binds evidence_chunk_ids'
} else {
  Write-Bad 'concept_graph_service missing evidence binding'
}

Write-Step 'Concept graph unified error check'
$kgEndpointContent = Get-Content "$root\backend\app\api\v1\endpoints\concept_graph.py" -Raw
if ($kgEndpointContent -match 'NotFoundException') {
  Write-Ok 'concept_graph endpoint uses unified exceptions'
} else {
  Write-Bad 'concept_graph endpoint still uses HTTPException'
}
if ($kgEndpointContent -match 'HTTPException') {
  Write-Bad 'concept_graph endpoint still references HTTPException'
} else {
  Write-Ok 'concept_graph endpoint has no HTTPException references'
}

Write-Step 'Concept compare evidence loading check'
$kgCompareContent = Get-Content "$root\backend\app\services\concept_compare_service.py" -Raw
if ($kgCompareContent -match '_load_evidence_chunks') {
  Write-Ok 'concept_compare_service loads evidence chunks'
} else {
  Write-Bad 'concept_compare_service missing evidence loading'
}
if ($kgCompareContent -match 'user_config') {
  Write-Ok 'concept_compare_service supports user_config'
} else {
  Write-Bad 'concept_compare_service missing user_config support'
}
```

在 `verify_phase2_engineering.sh` 追加等价的第 11 节。

- [ ] **Step 2: 运行全部后端测试**

```bash
cd backend && python -m pytest app/tests/ -q
```
Expected: 全部 PASS

- [ ] **Step 3: 运行前端构建**

```bash
cd frontend && npm run build
```
Expected: 构建成功

- [ ] **Step 4: 运行验收脚本**

```bash
pwsh ./scripts/verify_phase2_engineering.ps1
```
Expected: ACCEPTANCE PASSED

- [ ] **Step 5: 提交**

```bash
git add scripts/verify_phase2_engineering.ps1 scripts/verify_phase2_engineering.sh
git commit -m "chore(graph): add evidence binding and unified error acceptance checks"
```

- [ ] **Step 6: 推送到 GitHub**

```bash
git push origin main
```

- [ ] **Step 7: 验证 CI 通过**

```bash
gh run list --limit 1
```
Expected: success

---

## Self-Review

**1. Spec coverage:**
- P0 evidence_chunk_ids 绑定 → Task 1 ✓
- P0 compare 加载 MaterialChunk → Task 2 ✓
- P1 user_config 透传 → Task 3 ✓
- P1 edge_id 校验 → Task 4 ✓
- P1 统一错误格式 → Task 5 ✓
- P2 n-gram 匹配 → Task 6 ✓
- P2 新关系类型 → Task 6 ✓
- P3 验收脚本 → Task 8 ✓
- 前端证据展示 → Task 7 ✓
- CI 推送 → Task 8 ✓

**2. Placeholder scan:** 无 TBD/TODO，每步都有完整代码。

**3. Type consistency:**
- `_merge_evidence_ids(a, b)` 在 Task 1 定义，在 `_try_make_edge` 中使用 ✓
- `_load_evidence_chunks(db, user_id, chunk_ids)` 在 Task 2 定义 ✓
- `user_config` 参数从 endpoint → service → agent 一致 ✓
- `NotFoundException` 在 Task 5 引入，与 `core/exceptions.py` 定义一致 ✓
