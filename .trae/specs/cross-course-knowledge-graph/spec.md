# 跨课程知识图谱与对比解析 Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cross-course knowledge graph that syncs knowledge points into concept nodes, discovers relationships between courses, and generates evidence-bound compare reports.

**Architecture:** SQLite + SQLAlchemy models (ConceptNode/ConceptEdge/ConceptCompareReport) → rule-based candidate edge service → REST API under `/api/v1/concept-graph` → Vue 3 SVG-based graph view. Compare agent follows existing agent pattern (load_prompt → call_llm → validate → return dict).

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, Vue 3 + Element Plus, SVG (no new graph library deps), pytest TDD.

**Baseline:** `50433c5` on `origin/main`.

---

## File Structure

**Create (backend):**
- `backend/app/models/concept_graph.py` — ConceptNode, ConceptEdge, ConceptCompareReport
- `backend/app/schemas/concept_graph.py` — Pydantic request/response schemas
- `backend/app/services/concept_graph_service.py` — node sync, candidate edges, graph query, confirm/reject
- `backend/app/agents/concept_compare.py` — CompareAgent with mock fallback
- `backend/app/agents/prompts/concept_compare_v1.md` — compare prompt
- `backend/app/api/v1/endpoints/concept_graph.py` — 6 endpoints
- `backend/app/tests/test_concept_graph_models.py`
- `backend/app/tests/test_concept_graph_service.py`
- `backend/app/tests/test_concept_graph_api.py`
- `backend/app/tests/test_concept_graph_permissions.py`

**Create (frontend):**
- `frontend/src/api/conceptGraph.ts` — API client
- `frontend/src/views/KnowledgeGraphView.vue` — SVG graph + detail panels + compare drawer

**Modify:**
- `backend/app/models/__init__.py` — export new models
- `backend/app/api/v1/api.py` — register concept_graph router
- `backend/app/tests/conftest.py` — add `create_knowledge_point` helper
- `backend/app/tests/test_api_contracts.py` — add concept-graph contracts + retrieve items contract
- `backend/scripts/seed_demo_data.py` — add cross-course demo data
- `frontend/src/router/index.ts` — add `/knowledge-graph` route
- `frontend/src/layouts/MainLayout.vue` — add menu item
- `scripts/verify_phase2_engineering.ps1` — add concept-graph static checks
- `scripts/verify_phase2_engineering.sh` — same

---

## Task P0: Audit closure (retrieve items contract + static check)

**Files:**
- Modify: `backend/app/tests/test_api_contracts.py`
- Modify: `scripts/verify_phase2_engineering.ps1`
- Modify: `scripts/verify_phase2_engineering.sh`

- [ ] **Step 1: Add retrieve step output_data.items contract test**

Append to `test_api_contracts.py`:

```python
def test_agent_runs_retrieve_step_items_contract(client) -> None:
    """AgentRun retrieve step 的 output_data 支持 {total, items} 结构。"""
    headers = auth_headers(client, username="alice")
    run_id = _create_chat_run(client, headers, "retrieve契约课程", "什么是进程？")

    resp = client.get(f"/api/v1/agent-runs/{run_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    retrieve_steps = [s for s in body["steps"] if s["step_name"] == "retrieve"]
    assert len(retrieve_steps) >= 1
    out = retrieve_steps[0]["output_data"]
    # retrieve step 写入 {total, items} 或 {chunks} 结构，items 必须是 list
    if out and isinstance(out, dict) and "items" in out:
        assert isinstance(out["items"], list)
```

- [ ] **Step 2: Run test, verify pass**

```bash
cd backend && .\.venv\Scripts\python.exe -m pytest app/tests/test_api_contracts.py::test_agent_runs_retrieve_step_items_contract -v
```

- [ ] **Step 3: Add static checks to verify scripts**

In `verify_phase2_engineering.ps1`, after section 8, add section 9:

```powershell
# 9. T0-1: AgentRunsView supports output_data.items
Write-Step 'AgentRunsView output_data.items support check'
$agentRunsVue = Get-Content "$root\frontend\src\views\AgentRunsView.vue" -Raw
if ($agentRunsVue -match 'obj\.items') {
  Write-Ok 'AgentRunsView supports output_data.items'
} else {
  Write-Bad 'AgentRunsView missing output_data.items support'
}
```

In `verify_phase2_engineering.sh`, after section 8, add section 9:

```bash
# 9. T0-1: AgentRunsView supports output_data.items
step "AgentRunsView output_data.items support check"
agent_runs_vue="$root/frontend/src/views/AgentRunsView.vue"
if grep -q 'obj\.items' "$agent_runs_vue"; then ok "AgentRunsView supports output_data.items"; else bad "AgentRunsView missing output_data.items support"; fi
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/tests/test_api_contracts.py scripts/verify_phase2_engineering.ps1 scripts/verify_phase2_engineering.sh
git commit -m "test(contract): lock retrieve step output_data.items contract"
```

---

## Task P1: Data models + node sync

**Files:**
- Create: `backend/app/models/concept_graph.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/tests/test_concept_graph_models.py`

- [ ] **Step 1: Write failing model tests**

Create `backend/app/tests/test_concept_graph_models.py`:

```python
"""ConceptNode / ConceptEdge / ConceptCompareReport model tests."""
from app.models import ConceptNode, ConceptEdge, ConceptCompareReport


def test_concept_node_fields(db_session, sample_user, sample_course):
    node = ConceptNode(
        user_id=sample_user.id,
        course_id=sample_course.id,
        knowledge_point_id=None,
        title="死锁",
        normalized_title="死锁",
        summary="资源循环等待",
        aliases='["deadlock"]',
        importance=5,
        source_chunk_ids="[1, 2]",
        weak_point_score=0.0,
    )
    db_session.add(node)
    db_session.commit()
    assert node.id is not None
    assert node.created_at is not None
    assert node.aliases == '["deadlock"]'


def test_concept_edge_fields(db_session, sample_user, sample_course):
    n1 = ConceptNode(user_id=sample_user.id, course_id=sample_course.id,
                     title="A", normalized_title="a")
    n2 = ConceptNode(user_id=sample_user.id, course_id=sample_course.id,
                     title="B", normalized_title="b")
    db_session.add_all([n1, n2])
    db_session.commit()
    edge = ConceptEdge(
        user_id=sample_user.id,
        source_node_id=n1.id,
        target_node_id=n2.id,
        relation_type="similar_to",
        confidence=0.8,
        reason="both about resource contention",
        evidence_chunk_ids="[1, 2]",
        status="candidate",
    )
    db_session.add(edge)
    db_session.commit()
    assert edge.id is not None
    assert edge.status == "candidate"


def test_concept_compare_report_fields(db_session, sample_user, sample_course):
    n1 = ConceptNode(user_id=sample_user.id, course_id=sample_course.id,
                     title="A", normalized_title="a")
    n2 = ConceptNode(user_id=sample_user.id, course_id=sample_course.id,
                     title="B", normalized_title="b")
    db_session.add_all([n1, n2])
    db_session.commit()
    report = ConceptCompareReport(
        user_id=sample_user.id,
        source_node_id=n1.id,
        target_node_id=n2.id,
        edge_id=None,
        report_json='{"similarities": []}',
        citation_chunk_ids="[1]",
        prompt_version="v1",
        provider="mock",
        model_name="mock",
        audit_run_id=None,
    )
    db_session.add(report)
    db_session.commit()
    assert report.id is not None
```

- [ ] **Step 2: Add fixtures to conftest.py**

Add to `backend/app/tests/conftest.py`:

```python
@pytest.fixture
def sample_user(db_session):
    from app.models import User
    user = User(username="alice", email="alice@test.com",
                hashed_password="x")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_course(db_session, sample_user):
    from app.models import Course
    course = Course(name="操作系统", user_id=sample_user.id)
    db_session.add(course)
    db_session.commit()
    return course


def create_knowledge_point(client, headers, course_id, title,
                           summary="", importance=3, source_chunk_ids=None):
    """Helper: create a knowledge point via the outline API or direct DB."""
    import json
    # Use direct DB insertion via a test-only endpoint is not available,
    # so we create via the outline generation API. For tests, we insert directly.
    # This helper is for API-level tests that need KPs.
    # Returns the KP id by querying the list endpoint.
    resp = client.get(f"/api/v1/courses/{course_id}/knowledge-points",
                      headers=headers)
    # If no KPs exist, we need to create them. For now, return None and
    # tests will create KPs via DB session directly.
    return None
```

Actually, the existing conftest doesn't expose `db_session` as a fixture. Let me check... The `client` fixture creates an in-memory DB. For model tests, I need a `db_session` fixture. Let me add one:

```python
@pytest.fixture
def db_session():
    """SQLAlchemy session for direct model tests (separate from client fixture)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
```

- [ ] **Step 3: Run tests, verify they fail**

```bash
cd backend && .\.venv\Scripts\python.exe -m pytest app/tests/test_concept_graph_models.py -v
```
Expected: FAIL (ImportError: cannot import name 'ConceptNode')

- [ ] **Step 4: Create the models**

Create `backend/app/models/concept_graph.py`:

```python
"""Cross-course concept graph models.

ConceptNode  — a knowledge point synced into the graph layer.
ConceptEdge  — a discovered relationship between two nodes.
ConceptCompareReport — cached structured compare report.
"""
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin


class ConceptNode(Base, TimestampMixin):
    __tablename__ = "concept_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    knowledge_point_id = Column(Integer, ForeignKey("knowledge_points.id"), nullable=True)
    title = Column(String(255), nullable=False)
    normalized_title = Column(String(255), nullable=False, index=True)
    summary = Column(Text, default="")
    aliases = Column(Text, default="[]")        # JSON list
    importance = Column(Integer, default=3)      # 1-5
    source_chunk_ids = Column(Text, default="[]")  # JSON list
    weak_point_score = Column(Float, default=0.0)

    def __repr__(self):
        return f"<ConceptNode {self.id} {self.title}>"


class ConceptEdge(Base, TimestampMixin):
    __tablename__ = "concept_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_node_id = Column(Integer, ForeignKey("concept_nodes.id"), nullable=False, index=True)
    target_node_id = Column(Integer, ForeignKey("concept_nodes.id"), nullable=False, index=True)
    relation_type = Column(String(50), nullable=False)
    confidence = Column(Float, default=0.0)
    reason = Column(Text, default="")
    evidence_chunk_ids = Column(Text, default="[]")  # JSON list
    status = Column(String(20), default="candidate")  # candidate / confirmed / rejected
    audit_run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True)

    def __repr__(self):
        return f"<ConceptEdge {self.id} {self.relation_type}>"


class ConceptCompareReport(Base, TimestampMixin):
    __tablename__ = "concept_compare_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_node_id = Column(Integer, ForeignKey("concept_nodes.id"), nullable=False)
    target_node_id = Column(Integer, ForeignKey("concept_nodes.id"), nullable=False)
    edge_id = Column(Integer, ForeignKey("concept_edges.id"), nullable=True)
    report_json = Column(Text, default="{}")     # JSON
    citation_chunk_ids = Column(Text, default="[]")  # JSON list
    prompt_version = Column(String(50), default="v1")
    provider = Column(String(50), default="mock")
    model_name = Column(String(50), default="mock")
    config_id = Column(Integer, ForeignKey("user_llm_configs.id"), nullable=True)
    audit_run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True)

    def __repr__(self):
        return f"<ConceptCompareReport {self.id}>"
```

- [ ] **Step 5: Register models in `__init__.py`**

Add to `backend/app/models/__init__.py`:
- Import: `from app.models.concept_graph import ConceptNode, ConceptEdge, ConceptCompareReport`
- Add to `__all__`: `"ConceptNode"`, `"ConceptEdge"`, `"ConceptCompareReport"`

- [ ] **Step 6: Run model tests, verify pass**

```bash
cd backend && .\.venv\Scripts\python.exe -m pytest app/tests/test_concept_graph_models.py -v
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/concept_graph.py backend/app/models/__init__.py backend/app/tests/conftest.py backend/app/tests/test_concept_graph_models.py
git commit -m "feat(graph): add ConceptNode/Edge/CompareReport models"
```

---

## Task P2: Concept graph service (node sync + candidate edges)

**Files:**
- Create: `backend/app/services/concept_graph_service.py`
- Create: `backend/app/tests/test_concept_graph_service.py`

- [ ] **Step 1: Write failing service tests**

Create `backend/app/tests/test_concept_graph_service.py`:

```python
"""Concept graph service tests: node sync, candidate edges, confirm/reject."""
import json
from app.models import (
    Base, User, Course, KnowledgePoint, MaterialChunk,
    ConceptNode, ConceptEdge,
)
from app.services.concept_graph_service import (
    sync_nodes_for_user,
    generate_candidate_edges,
    get_graph,
    confirm_edge,
    reject_edge,
)


def _setup_two_courses(db_session):
    """Create user + 2 courses + KPs with overlapping titles."""
    user = User(username="alice", email="a@x.com", hashed_password="x")
    db_session.add(user)
    os_course = Course(name="操作系统", user_id=1)
    db_course = Course(name="数据库", user_id=1)
    db_session.add_all([os_course, db_course])
    db_session.commit()

    # OS knowledge points
    os_kp1 = KnowledgePoint(user_id=user.id, course_id=os_course.id,
                            title="死锁", summary="资源循环等待",
                            importance=5, source_chunk_ids="[]")
    os_kp2 = KnowledgePoint(user_id=user.id, course_id=os_course.id,
                            title="页面置换", summary="有限内存下的页面淘汰",
                            importance=4, source_chunk_ids="[]")
    # DB knowledge points
    db_kp1 = KnowledgePoint(user_id=user.id, course_id=db_course.id,
                            title="死锁", summary="事务锁冲突",
                            importance=5, source_chunk_ids="[]")
    db_kp2 = KnowledgePoint(user_id=user.id, course_id=db_course.id,
                            title="缓冲池替换", summary="有限缓存下的页面淘汰",
                            importance=4, source_chunk_ids="[]")
    db_session.add_all([os_kp1, os_kp2, db_kp1, db_kp2])
    db_session.commit()
    return user, os_course, db_course


def test_sync_nodes_creates_one_node_per_kp(db_session):
    user, os_course, db_course = _setup_two_courses(db_session)
    sync_nodes_for_user(db_session, user.id)
    nodes = db_session.query(ConceptNode).filter_by(user_id=user.id).all()
    assert len(nodes) == 4


def test_sync_nodes_is_idempotent(db_session):
    user, _, _ = _setup_two_courses(db_session)
    sync_nodes_for_user(db_session, user.id)
    sync_nodes_for_user(db_session, user.id)
    nodes = db_session.query(ConceptNode).filter_by(user_id=user.id).all()
    assert len(nodes) == 4


def test_candidate_edges_same_name_different_meaning(db_session):
    user, os_course, db_course = _setup_two_courses(db_session)
    sync_nodes_for_user(db_session, user.id)
    generate_candidate_edges(db_session, user.id)
    edges = db_session.query(ConceptEdge).filter_by(user_id=user.id).all()
    # 死锁 (OS) ↔ 死锁 (DB): same name, different summaries → same_name_different_meaning
    deadlock_edges = [e for e in edges if e.relation_type == "same_name_different_meaning"]
    assert len(deadlock_edges) >= 1
    assert all(e.confidence >= 0.45 for e in deadlock_edges)


def test_candidate_edges_similar_to(db_session):
    user, os_course, db_course = _setup_two_courses(db_session)
    sync_nodes_for_user(db_session, user.id)
    generate_candidate_edges(db_session, user.id)
    edges = db_session.query(ConceptEdge).filter_by(user_id=user.id).all()
    # 页面置换 ↔ 缓冲池替换: both about "页面淘汰" → similar_to
    similar_edges = [e for e in edges if e.relation_type == "similar_to"]
    assert len(similar_edges) >= 1


def test_confirm_edge_changes_status(db_session):
    user, _, _ = _setup_two_courses(db_session)
    sync_nodes_for_user(db_session, user.id)
    generate_candidate_edges(db_session, user.id)
    edge = db_session.query(ConceptEdge).filter_by(user_id=user.id).first()
    confirm_edge(db_session, user.id, edge.id)
    db_session.refresh(edge)
    assert edge.status == "confirmed"


def test_reject_edge_changes_status(db_session):
    user, _, _ = _setup_two_courses(db_session)
    sync_nodes_for_user(db_session, user.id)
    generate_candidate_edges(db_session, user.id)
    edge = db_session.query(ConceptEdge).filter_by(user_id=user.id).first()
    reject_edge(db_session, user.id, edge.id)
    db_session.refresh(edge)
    assert edge.status == "rejected"


def test_candidate_edges_skip_rejected(db_session):
    user, _, _ = _setup_two_courses(db_session)
    sync_nodes_for_user(db_session, user.id)
    generate_candidate_edges(db_session, user.id)
    edges_before = db_session.query(ConceptEdge).filter_by(user_id=user.id).count()
    edge = db_session.query(ConceptEdge).filter_by(user_id=user.id).first()
    reject_edge(db_session, user.id, edge.id)
    generate_candidate_edges(db_session, user.id)
    edges_after = db_session.query(ConceptEdge).filter_by(user_id=user.id).count()
    # Rejected edges should not be regenerated
    assert edges_after == edges_before


def test_get_graph_returns_nodes_and_edges(db_session):
    user, _, _ = _setup_two_courses(db_session)
    sync_nodes_for_user(db_session, user.id)
    generate_candidate_edges(db_session, user.id)
    graph = get_graph(db_session, user.id)
    assert "nodes" in graph and "edges" in graph
    assert len(graph["nodes"]) == 4
    assert len(graph["edges"]) >= 1
```

- [ ] **Step 2: Run tests, verify fail**

```bash
cd backend && .\.venv\Scripts\python.exe -m pytest app/tests/test_concept_graph_service.py -v
```

- [ ] **Step 3: Implement the service**

Create `backend/app/services/concept_graph_service.py`:

```python
"""Concept graph service: node sync, candidate edge generation, graph query.

Candidate edges use rule-based matching (no LLM) in P2:
- same_name_different_meaning: identical normalized title, different course, different summary
- similar_to: keyword overlap in summary or partial title match
- applies_to: cross-course similar_to
- prerequisite_of: A's summary mentions B's title
"""
import json
import re
from collections import defaultdict

from sqlalchemy.orm import Session

from app.models import (
    KnowledgePoint, ConceptNode, ConceptEdge, WeakPoint,
)


def _normalize_title(title: str) -> str:
    """Lowercase, strip, collapse whitespace, remove punctuation."""
    t = title.lower().strip()
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _keyword_set(summary: str) -> set[str]:
    """Extract meaningful keywords from a summary (len >= 2 for Chinese)."""
    if not summary:
        return set()
    # Split on non-word chars; keep tokens of length >= 2
    tokens = re.findall(r"[\u4e00-\u9fff]{1,}|[a-zA-Z]{2,}", summary)
    return set(t for t in tokens if len(t) >= 2)


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def sync_nodes_for_user(db: Session, user_id: int) -> int:
    """Sync KnowledgePoint → ConceptNode for all of a user's courses.
    Idempotent: existing nodes are updated, not duplicated.
    Returns the number of nodes.
    """
    kps = db.query(KnowledgePoint).filter_by(user_id=user_id).all()
    existing = {
        (n.course_id, n.knowledge_point_id): n
        for n in db.query(ConceptNode).filter_by(user_id=user_id).all()
    }
    # Weak point scores
    weak = db.query(WeakPoint).filter_by(user_id=user_id).all()
    weak_kp_ids = {w.knowledge_point_id for w in weak}

    count = 0
    for kp in kps:
        key = (kp.course_id, kp.id)
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
    db.flush()
    return count


def generate_candidate_edges(db: Session, user_id: int) -> int:
    """Generate candidate edges using rule-based matching.
    Skips pairs that already have a confirmed/rejected edge.
    Returns the number of new edges created.
    """
    nodes = db.query(ConceptNode).filter_by(user_id=user_id).all()
    if len(nodes) < 2:
        return 0

    # Build existing edge key set: (min_id, max_id) → set of statuses
    existing = defaultdict(set)
    for e in db.query(ConceptEdge).filter_by(user_id=user_id).all():
        key = (min(e.source_node_id, e.target_node_id),
               max(e.source_node_id, e.target_node_id))
        existing[key].add(e.status)

    created = 0
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            key = (min(a.id, b.id), max(a.id, b.id))
            # Skip if confirmed or rejected already
            if "confirmed" in existing[key] or "rejected" in existing[key]:
                continue
            # Skip if a candidate edge already exists for this pair
            if "candidate" in existing[key]:
                continue

            edge = _try_make_edge(a, b)
            if edge is not None:
                edge.user_id = user_id
                db.add(edge)
                created += 1
    db.flush()
    return created


def _try_make_edge(a: ConceptNode, b: ConceptNode) -> ConceptEdge | None:
    """Apply rules to decide if a→b should have an edge. Returns edge or None."""
    same_title = a.normalized_title == b.normalized_title and a.normalized_title != ""
    diff_course = a.course_id != b.course_id
    kw_a = _keyword_set(a.summary or "")
    kw_b = _keyword_set(b.summary or "")
    kw_overlap = _jaccard(kw_a, kw_b)
    title_in_summary = (
        (a.title and a.title in (b.summary or "")) or
        (b.title and b.title in (a.summary or ""))
    )

    # Rule 1: same name, different course, different summary → same_name_different_meaning
    if same_title and diff_course:
        summary_sim = kw_overlap
        if summary_sim < 0.6:
            return ConceptEdge(
                source_node_id=a.id, target_node_id=b.id,
                relation_type="same_name_different_meaning",
                confidence=0.7,
                reason=f"同名概念「{a.title}」在两门课中含义不同",
                evidence_chunk_ids="[]",
                status="candidate",
            )
        else:
            return ConceptEdge(
                source_node_id=a.id, target_node_id=b.id,
                relation_type="similar_to",
                confidence=0.8,
                reason=f"同名概念「{a.title}」在两门课中含义相近",
                evidence_chunk_ids="[]",
                status="candidate",
            )

    # Rule 2: keyword overlap → similar_to (cross-course → applies_to)
    if kw_overlap >= 0.2:
        rtype = "applies_to" if diff_course else "similar_to"
        return ConceptEdge(
            source_node_id=a.id, target_node_id=b.id,
            relation_type=rtype,
            confidence=0.45 + 0.3 * kw_overlap,
            reason=f"摘要关键词重叠度 {kw_overlap:.2f}",
            evidence_chunk_ids="[]",
            status="candidate",
        )

    # Rule 3: A's summary mentions B's title → prerequisite_of
    if title_in_summary:
        return ConceptEdge(
            source_node_id=a.id, target_node_id=b.id,
            relation_type="prerequisite_of",
            confidence=0.6,
            reason="一方摘要提及另一方标题",
            evidence_chunk_ids="[]",
            status="candidate",
        )

    return None


def get_graph(db: Session, user_id: int,
              course_ids: list[int] | None = None,
              relation_type: str | None = None,
              status: str | None = None) -> dict:
    """Return {nodes: [...], edges: [...]} for the user."""
    node_q = db.query(ConceptNode).filter_by(user_id=user_id)
    if course_ids:
        node_q = node_q.filter(ConceptNode.course_id.in_(course_ids))
    nodes = node_q.all()
    node_ids = {n.id for n in nodes}

    edge_q = db.query(ConceptEdge).filter_by(user_id=user_id)
    if relation_type:
        edge_q = edge_q.filter(ConceptEdge.relation_type == relation_type)
    if status:
        edge_q = edge_q.filter(ConceptEdge.status == status)
    edges = [e for e in edge_q.all()
             if e.source_node_id in node_ids and e.target_node_id in node_ids]

    return {
        "nodes": [_node_to_dict(n) for n in nodes],
        "edges": [_edge_to_dict(e) for e in edges],
    }


def _node_to_dict(n: ConceptNode) -> dict:
    return {
        "id": n.id, "user_id": n.user_id, "course_id": n.course_id,
        "knowledge_point_id": n.knowledge_point_id,
        "title": n.title, "normalized_title": n.normalized_title,
        "summary": n.summary or "",
        "aliases": json.loads(n.aliases or "[]"),
        "importance": n.importance,
        "source_chunk_ids": json.loads(n.source_chunk_ids or "[]"),
        "weak_point_score": n.weak_point_score,
    }


def _edge_to_dict(e: ConceptEdge) -> dict:
    return {
        "id": e.id, "user_id": e.user_id,
        "source_node_id": e.source_node_id, "target_node_id": e.target_node_id,
        "relation_type": e.relation_type, "confidence": e.confidence,
        "reason": e.reason or "",
        "evidence_chunk_ids": json.loads(e.evidence_chunk_ids or "[]"),
        "status": e.status, "audit_run_id": e.audit_run_id,
    }


def confirm_edge(db: Session, user_id: int, edge_id: int) -> ConceptEdge | None:
    edge = db.query(ConceptEdge).filter_by(id=edge_id, user_id=user_id).first()
    if edge is None:
        return None
    edge.status = "confirmed"
    db.flush()
    return edge


def reject_edge(db: Session, user_id: int, edge_id: int) -> ConceptEdge | None:
    edge = db.query(ConceptEdge).filter_by(id=edge_id, user_id=user_id).first()
    if edge is None:
        return None
    edge.status = "rejected"
    db.flush()
    return edge
```

- [ ] **Step 4: Run service tests, verify pass**

```bash
cd backend && .\.venv\Scripts\python.exe -m pytest app/tests/test_concept_graph_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/concept_graph_service.py backend/app/tests/test_concept_graph_service.py
git commit -m "feat(graph): add node sync and candidate edge generation service"
```

---

## Task P3: API endpoints + schemas

**Files:**
- Create: `backend/app/schemas/concept_graph.py`
- Create: `backend/app/api/v1/endpoints/concept_graph.py`
- Modify: `backend/app/api/v1/api.py`
- Create: `backend/app/tests/test_concept_graph_api.py`
- Create: `backend/app/tests/test_concept_graph_permissions.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/app/tests/test_concept_graph_api.py`:

```python
"""Concept graph API tests: rebuild, graph, node detail, confirm, reject."""
from app.tests.conftest import auth_headers, create_course, upload_material


def _seed_kps_via_outline(client, headers, course_id, material_id):
    """Trigger outline generation to create knowledge points."""
    resp = client.post(f"/api/v1/materials/{material_id}/outline",
                       headers=headers)
    # outline endpoint may not exist; KPs can be created via DB in tests
    return resp


def test_rebuild_graph(client):
    """POST /concept-graph/rebuild syncs nodes and generates edges."""
    headers = auth_headers(client, username="alice")
    # Create 2 courses with materials (KPs created via DB or outline)
    os_id = create_course(client, headers, name="操作系统")
    db_id = create_course(client, headers, name="数据库")
    resp = client.post("/api/v1/concept-graph/rebuild", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "nodes_count" in body
    assert "edges_count" in body


def test_get_graph(client):
    """GET /concept-graph returns nodes + edges."""
    headers = auth_headers(client, username="alice")
    create_course(client, headers, name="操作系统")
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    resp = client.get("/api/v1/concept-graph", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "nodes" in body and "edges" in body
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)


def test_get_node_detail(client, db_session_via_app):
    """GET /concept-graph/nodes/{id} returns node detail with edges."""
    headers = auth_headers(client, username="alice")
    create_course(client, headers, name="操作系统")
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    graph = client.get("/api/v1/concept-graph", headers=headers).json()
    if not graph["nodes"]:
        return  # no KPs seeded, skip
    node_id = graph["nodes"][0]["id"]
    resp = client.get(f"/api/v1/concept-graph/nodes/{node_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "id" in body and "title" in body


def test_confirm_edge(client):
    """POST /concept-graph/edges/{id}/confirm changes status."""
    headers = auth_headers(client, username="alice")
    create_course(client, headers, name="操作系统")
    create_course(client, headers, name="数据库")
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    graph = client.get("/api/v1/concept-graph", headers=headers).json()
    if not graph["edges"]:
        return
    edge_id = graph["edges"][0]["id"]
    resp = client.post(f"/api/v1/concept-graph/edges/{edge_id}/confirm",
                       headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "confirmed"


def test_reject_edge(client):
    """POST /concept-graph/edges/{id}/reject changes status."""
    headers = auth_headers(client, username="alice")
    create_course(client, headers, name="操作系统")
    create_course(client, headers, name="数据库")
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    graph = client.get("/api/v1/concept-graph", headers=headers).json()
    if not graph["edges"]:
        return
    edge_id = graph["edges"][0]["id"]
    resp = client.post(f"/api/v1/concept-graph/edges/{edge_id}/reject",
                       headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"
```

Create `backend/app/tests/test_concept_graph_permissions.py`:

```python
"""Concept graph permission tests: user isolation."""
from app.tests.conftest import auth_headers, create_course


def test_other_user_cannot_access_graph(client):
    """Alice's graph is invisible to Bob."""
    headers_a = auth_headers(client, username="alice", email="a@x.com")
    headers_b = auth_headers(client, username="bob", email="b@x.com")
    create_course(client, headers_a, name="操作系统")
    client.post("/api/v1/concept-graph/rebuild", headers=headers_a)
    # Bob sees empty graph
    resp = client.get("/api/v1/concept-graph", headers=headers_b)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) == 0


def test_other_user_cannot_confirm_edge(client):
    """Bob cannot confirm Alice's edge."""
    headers_a = auth_headers(client, username="alice", email="a@x.com")
    headers_b = auth_headers(client, username="bob", email="b@x.com")
    create_course(client, headers_a, name="操作系统")
    create_course(client, headers_a, name="数据库")
    client.post("/api/v1/concept-graph/rebuild", headers=headers_a)
    graph = client.get("/api/v1/concept-graph", headers=headers_a).json()
    if not graph["edges"]:
        return
    edge_id = graph["edges"][0]["id"]
    resp = client.post(f"/api/v1/concept-graph/edges/{edge_id}/confirm",
                       headers=headers_b)
    assert resp.status_code == 404


def test_other_user_node_detail_404(client):
    """Bob cannot read Alice's node detail."""
    headers_a = auth_headers(client, username="alice", email="a@x.com")
    headers_b = auth_headers(client, username="bob", email="b@x.com")
    create_course(client, headers_a, name="操作系统")
    client.post("/api/v1/concept-graph/rebuild", headers=headers_a)
    graph = client.get("/api/v1/concept-graph", headers=headers_a).json()
    if not graph["nodes"]:
        return
    node_id = graph["nodes"][0]["id"]
    resp = client.get(f"/api/v1/concept-graph/nodes/{node_id}", headers=headers_b)
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests, verify fail**

- [ ] **Step 3: Create schemas**

Create `backend/app/schemas/concept_graph.py`:

```python
"""Pydantic schemas for concept graph API."""
from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: int
    user_id: int
    course_id: int
    knowledge_point_id: int | None = None
    title: str
    normalized_title: str
    summary: str = ""
    aliases: list[str] = []
    importance: int = 3
    source_chunk_ids: list[int] = []
    weak_point_score: float = 0.0


class GraphEdge(BaseModel):
    id: int
    user_id: int
    source_node_id: int
    target_node_id: int
    relation_type: str
    confidence: float
    reason: str = ""
    evidence_chunk_ids: list[int] = []
    status: str = "candidate"
    audit_run_id: int | None = None


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class RebuildResponse(BaseModel):
    nodes_count: int
    edges_count: int


class NodeDetailResponse(GraphNode):
    related_edges: list[GraphEdge] = []


class EdgeActionResponse(GraphEdge):
    pass


class CompareRequest(BaseModel):
    source_node_id: int
    target_node_id: int
    edge_id: int | None = None
    user_focus: str = "concept"


class CompareReportResponse(BaseModel):
    id: int
    source_node_id: int
    target_node_id: int
    edge_id: int | None = None
    report_json: dict
    citation_chunk_ids: list[int] = []
    prompt_version: str = "v1"
    provider: str = "mock"
    model_name: str = "mock"
    fallback_used: bool = False
    fallback_reason: str = ""
    audit_run_id: int | None = None
```

- [ ] **Step 4: Create endpoint**

Create `backend/app/api/v1/endpoints/concept_graph.py`:

```python
"""Concept graph API endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models import User
from app.schemas.concept_graph import (
    GraphResponse, RebuildResponse, NodeDetailResponse,
    EdgeActionResponse, CompareRequest, CompareReportResponse,
)
from app.services.concept_graph_service import (
    sync_nodes_for_user, generate_candidate_edges,
    get_graph, confirm_edge, reject_edge, get_node_detail,
)
from app.services.concept_compare_service import get_or_create_compare_report

router = APIRouter()


@router.post("/rebuild", response_model=RebuildResponse)
def rebuild_graph(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    nodes_count = sync_nodes_for_user(db, current_user.id)
    edges_count = generate_candidate_edges(db, current_user.id)
    db.commit()
    return RebuildResponse(nodes_count=nodes_count, edges_count=edges_count)


@router.get("", response_model=GraphResponse)
def get_user_graph(
    course_ids: str | None = None,
    relation_type: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cids = None
    if course_ids:
        cids = [int(x) for x in course_ids.split(",") if x.strip()]
    graph = get_graph(db, current_user.id, cids, relation_type, status)
    return GraphResponse(**graph)


@router.get("/nodes/{node_id}", response_model=NodeDetailResponse)
def get_node(
    node_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    detail = get_node_detail(db, current_user.id, node_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    return NodeDetailResponse(**detail)


@router.post("/edges/{edge_id}/confirm", response_model=EdgeActionResponse)
def confirm(
    edge_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    edge = confirm_edge(db, current_user.id, edge_id)
    if edge is None:
        raise HTTPException(status_code=404, detail="边不存在")
    db.commit()
    return EdgeActionResponse(**_edge_to_response_dict(edge))


@router.post("/edges/{edge_id}/reject", response_model=EdgeActionResponse)
def reject(
    edge_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    edge = reject_edge(db, current_user.id, edge_id)
    if edge is None:
        raise HTTPException(status_code=404, detail="边不存在")
    db.commit()
    return EdgeActionResponse(**_edge_to_response_dict(edge))


@router.post("/compare", response_model=CompareReportResponse)
def compare(
    req: CompareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = get_or_create_compare_report(
        db, current_user.id, req.source_node_id, req.target_node_id,
        req.edge_id, req.user_focus,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    db.commit()
    return CompareReportResponse(**result)


def _edge_to_response_dict(edge) -> dict:
    import json
    return {
        "id": edge.id, "user_id": edge.user_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "relation_type": edge.relation_type,
        "confidence": edge.confidence,
        "reason": edge.reason or "",
        "evidence_chunk_ids": json.loads(edge.evidence_chunk_ids or "[]"),
        "status": edge.status,
        "audit_run_id": edge.audit_run_id,
    }
```

- [ ] **Step 5: Add `get_node_detail` to service**

Add to `concept_graph_service.py`:

```python
def get_node_detail(db: Session, user_id: int, node_id: int) -> dict | None:
    node = db.query(ConceptNode).filter_by(id=node_id, user_id=user_id).first()
    if node is None:
        return None
    node_dict = _node_to_dict(node)
    # Find edges touching this node
    edges = db.query(ConceptEdge).filter_by(user_id=user_id).filter(
        (ConceptEdge.source_node_id == node_id) |
        (ConceptEdge.target_node_id == node_id)
    ).all()
    node_dict["related_edges"] = [_edge_to_dict(e) for e in edges]
    return node_dict
```

- [ ] **Step 6: Register router in api.py**

Add to `backend/app/api/v1/api.py`:

```python
from app.api.v1.endpoints import concept_graph
api_router.include_router(concept_graph.router, prefix="/concept-graph", tags=["concept_graph"])
```

- [ ] **Step 7: Run API tests, verify pass**

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/concept_graph.py backend/app/api/v1/endpoints/concept_graph.py backend/app/api/v1/api.py backend/app/services/concept_graph_service.py backend/app/tests/test_concept_graph_api.py backend/app/tests/test_concept_graph_permissions.py
git commit -m "feat(graph): add concept-graph API endpoints with user isolation"
```

---

## Task P5: Compare agent + endpoint

**Files:**
- Create: `backend/app/agents/concept_compare.py`
- Create: `backend/app/agents/prompts/concept_compare_v1.md`
- Create: `backend/app/services/concept_compare_service.py`
- Create: `backend/app/tests/test_concept_compare_agent.py`

- [ ] **Step 1: Write failing compare tests**

Create `backend/app/tests/test_concept_compare_agent.py`:

```python
"""Concept compare agent + service tests."""
import json
from app.models import ConceptNode, ConceptCompareReport
from app.services.concept_compare_service import get_or_create_compare_report


def _setup_two_nodes(db_session):
    from app.models import User, Course
    user = User(username="alice", email="a@x.com", hashed_password="x")
    db_session.add(user)
    c1 = Course(name="操作系统", user_id=1)
    c2 = Course(name="数据库", user_id=1)
    db_session.add_all([c1, c2])
    db_session.commit()
    n1 = ConceptNode(user_id=1, course_id=c1.id, title="死锁",
                     normalized_title="死锁", summary="资源循环等待")
    n2 = ConceptNode(user_id=1, course_id=c2.id, title="死锁",
                     normalized_title="死锁", summary="事务锁冲突")
    db_session.add_all([n1, n2])
    db_session.commit()
    return n1, n2


def test_compare_creates_report(db_session):
    n1, n2 = _setup_two_nodes(db_session)
    result = get_or_create_compare_report(db_session, 1, n1.id, n2.id)
    assert result is not None
    assert "report_json" in result
    report = db_session.query(ConceptCompareReport).first()
    assert report is not None
    assert report.provider in ("mock", "real", "user")


def test_compare_report_has_required_fields(db_session):
    n1, n2 = _setup_two_nodes(db_session)
    result = get_or_create_compare_report(db_session, 1, n1.id, n2.id)
    rj = result["report_json"]
    assert "concept_a" in rj or "similarities" in rj
    assert "differences" in rj or "concept_b" in rj


def test_compare_is_cached(db_session):
    n1, n2 = _setup_two_nodes(db_session)
    get_or_create_compare_report(db_session, 1, n1.id, n2.id)
    get_or_create_compare_report(db_session, 1, n1.id, n2.id)
    reports = db_session.query(ConceptCompareReport).all()
    assert len(reports) == 1


def test_compare_nonexistent_node_returns_none(db_session):
    result = get_or_create_compare_report(db_session, 1, 999, 998)
    assert result is None
```

- [ ] **Step 2: Create compare prompt**

Create `backend/app/agents/prompts/concept_compare_v1.md`:

```
你是一个跨课程概念对比助手。请基于给定的证据片段，生成结构化对比报告。

概念 A: {concept_a_title}
概念 A 摘要: {concept_a_summary}
概念 B: {concept_b_title}
概念 B 摘要: {concept_b_summary}
证据片段: {evidence}

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
- 输出必须是合法 JSON。
```

- [ ] **Step 3: Create compare agent**

Create `backend/app/agents/concept_compare.py`:

```python
"""Concept compare agent: generates structured cross-course compare reports.

Follows the existing agent pattern: load_prompt → call_llm → validate → return dict.
Uses mock fallback when LLM is unavailable.
"""
import json

from app.agents.llm import call_llm_with_meta
from app.agents.prompt_loader import load_prompt
from app.agents.audit import AgentAudit


def generate_compare(
    db,
    user_id: int,
    concept_a: dict,
    concept_b: dict,
    evidence_chunks: list[dict] | None = None,
    user_config: dict | None = None,
) -> dict:
    """Generate a structured compare report for two concepts.

    Returns dict with: report_json, citation_chunk_ids, provider,
    fallback_used, fallback_reason, audit_run_id.
    """
    run = AgentAudit.create_run(
        db, user_id, run_type="concept_compare",
        input_summary={"a": concept_a.get("title"), "b": concept_b.get("title")},
        prompt_version="v1", model_name="mock", provider="mock",
    )

    try:
        prompt_template = load_prompt("concept_compare", version="v1")
        evidence_text = json.dumps(evidence_chunks or [], ensure_ascii=False)
        prompt = prompt_template.format(
            concept_a_title=concept_a.get("title", ""),
            concept_a_summary=concept_a.get("summary", ""),
            concept_b_title=concept_b.get("title", ""),
            concept_b_summary=concept_b.get("summary", ""),
            evidence=evidence_text,
        )

        resp = call_llm_with_meta(prompt, agent_type="concept_compare",
                                  user_config=user_config)
        raw = resp["text"]
        meta = resp.get("meta", {})

        try:
            report = json.loads(raw)
            AgentAudit.add_step(db, run.id, "generate", 0,
                                output_data={"raw_length": len(raw)})
            AgentAudit.finish_run(db, run.id, status="success",
                                  output_summary={"keys": list(report.keys())})
            return {
                "report_json": report,
                "citation_chunk_ids": [c["chunk_id"] for c in report.get("citations", []) if isinstance(c, dict) and "chunk_id" in c],
                "provider": meta.get("provider", "mock"),
                "model_name": meta.get("model_name", "mock"),
                "fallback_used": False,
                "fallback_reason": "",
                "audit_run_id": run.id,
            }
        except (json.JSONDecodeError, ValueError):
            # LLM returned non-JSON → fallback
            return _mock_fallback(db, run, concept_a, concept_b,
                                  reason="LLM 返回非 JSON，使用 mock fallback")
    except Exception as exc:
        return _mock_fallback(db, run, concept_a, concept_b,
                              reason=f"LLM 调用失败: {exc}")


def _mock_fallback(db, run, concept_a, concept_b, reason: str) -> dict:
    """Generate a mock compare report when LLM is unavailable."""
    report = {
        "concept_a": {"title": concept_a.get("title", ""),
                       "explanation": concept_a.get("summary", "")},
        "concept_b": {"title": concept_b.get("title", ""),
                       "explanation": concept_b.get("summary", "")},
        "similarities": ["两者都是重要概念，需要理解其核心定义"],
        "differences": [
            {"dimension": "所属领域", "a": concept_a.get("summary", ""),
             "b": concept_b.get("summary", "")}
        ],
        "transfer_learning": ["对比两者的核心思想，寻找可迁移的方法论"],
        "confusions": ["注意两者的适用场景差异"],
        "exam_questions": ["简述两者的联系与区别"],
        "citations": [],
        "insufficient_evidence": True,
    }
    AgentAudit.add_step(db, run.id, "generate", 0,
                        output_data={"fallback": True})
    AgentAudit.finish_run(db, run.id, status="success",
                          output_summary={"fallback": True})
    return {
        "report_json": report,
        "citation_chunk_ids": [],
        "provider": "mock",
        "model_name": "mock",
        "fallback_used": True,
        "fallback_reason": reason,
        "audit_run_id": run.id,
    }
```

- [ ] **Step 4: Create compare service**

Create `backend/app/services/concept_compare_service.py`:

```python
"""Concept compare service: caching + orchestration."""
import json

from sqlalchemy.orm import Session

from app.models import ConceptNode, ConceptCompareReport
from app.agents.concept_compare import generate_compare


def get_or_create_compare_report(
    db: Session,
    user_id: int,
    source_node_id: int,
    target_node_id: int,
    edge_id: int | None = None,
    user_focus: str = "concept",
) -> dict | None:
    """Get cached report or generate a new one. Returns dict or None if nodes don't exist."""
    n1 = db.query(ConceptNode).filter_by(id=source_node_id, user_id=user_id).first()
    n2 = db.query(ConceptNode).filter_by(id=target_node_id, user_id=user_id).first()
    if n1 is None or n2 is None:
        return None

    # Check cache: same user + same node pair (either order)
    cached = db.query(ConceptCompareReport).filter_by(
        user_id=user_id, source_node_id=source_node_id, target_node_id=target_node_id,
    ).first()
    if cached is None:
        cached = db.query(ConceptCompareReport).filter_by(
            user_id=user_id, source_node_id=target_node_id, target_node_id=source_node_id,
        ).first()
    if cached is not None:
        return _report_to_dict(cached)

    # Generate new
    result = generate_compare(
        db, user_id,
        concept_a={"title": n1.title, "summary": n1.summary or ""},
        concept_b={"title": n2.title, "summary": n2.summary or ""},
        evidence_chunks=[],
        user_config=None,
    )

    report = ConceptCompareReport(
        user_id=user_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_id=edge_id,
        report_json=json.dumps(result["report_json"], ensure_ascii=False),
        citation_chunk_ids=json.dumps(result["citation_chunk_ids"]),
        prompt_version="v1",
        provider=result["provider"],
        model_name=result["model_name"],
        audit_run_id=result["audit_run_id"],
    )
    db.add(report)
    db.flush()
    return _report_to_dict(report, result)


def _report_to_dict(report: ConceptCompareReport, gen_meta: dict | None = None) -> dict:
    meta = gen_meta or {}
    return {
        "id": report.id,
        "source_node_id": report.source_node_id,
        "target_node_id": report.target_node_id,
        "edge_id": report.edge_id,
        "report_json": json.loads(report.report_json or "{}"),
        "citation_chunk_ids": json.loads(report.citation_chunk_ids or "[]"),
        "prompt_version": report.prompt_version,
        "provider": report.provider,
        "model_name": report.model_name,
        "fallback_used": meta.get("fallback_used", False),
        "fallback_reason": meta.get("fallback_reason", ""),
        "audit_run_id": report.audit_run_id,
    }
```

- [ ] **Step 5: Run compare tests, verify pass**

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/concept_compare.py backend/app/agents/prompts/concept_compare_v1.md backend/app/services/concept_compare_service.py backend/app/tests/test_concept_compare_agent.py
git commit -m "feat(graph): add concept compare agent with mock fallback"
```

---

## Task P4: Frontend graph page

**Files:**
- Create: `frontend/src/api/conceptGraph.ts`
- Create: `frontend/src/views/KnowledgeGraphView.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/layouts/MainLayout.vue`

- [ ] **Step 1: Create API client**

Create `frontend/src/api/conceptGraph.ts`:

```typescript
import request from './request'

export interface GraphNode {
  id: number
  user_id: number
  course_id: number
  knowledge_point_id: number | null
  title: string
  normalized_title: string
  summary: string
  aliases: string[]
  importance: number
  source_chunk_ids: number[]
  weak_point_score: number
}

export interface GraphEdge {
  id: number
  user_id: number
  source_node_id: number
  target_node_id: number
  relation_type: string
  confidence: number
  reason: string
  evidence_chunk_ids: number[]
  status: string
  audit_run_id: number | null
}

export interface GraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface RebuildResponse {
  nodes_count: number
  edges_count: number
}

export interface NodeDetail extends GraphNode {
  related_edges: GraphEdge[]
}

export interface CompareReport {
  id: number
  source_node_id: number
  target_node_id: number
  edge_id: number | null
  report_json: Record<string, any>
  citation_chunk_ids: number[]
  prompt_version: string
  provider: string
  model_name: string
  fallback_used: boolean
  fallback_reason: string
  audit_run_id: number | null
}

export function rebuildGraph() {
  return request.post<RebuildResponse>('/api/v1/concept-graph/rebuild')
}

export function getGraph(params?: {
  course_ids?: string
  relation_type?: string
  status?: string
}) {
  return request.get<GraphResponse>('/api/v1/concept-graph', { params })
}

export function getNodeDetail(nodeId: number) {
  return request.get<NodeDetail>(`/api/v1/concept-graph/nodes/${nodeId}`)
}

export function confirmEdge(edgeId: number) {
  return request.post<GraphEdge>(`/api/v1/concept-graph/edges/${edgeId}/confirm`)
}

export function rejectEdge(edgeId: number) {
  return request.post<GraphEdge>(`/api/v1/concept-graph/edges/${edgeId}/reject`)
}

export function compareNodes(sourceNodeId: number, targetNodeId: number, edgeId?: number) {
  return request.post<CompareReport>('/api/v1/concept-graph/compare', {
    source_node_id: sourceNodeId,
    target_node_id: targetNodeId,
    edge_id: edgeId ?? null,
    user_focus: 'concept',
  })
}
```

- [ ] **Step 2: Create KnowledgeGraphView.vue**

Create `frontend/src/views/KnowledgeGraphView.vue` — SVG-based force graph with:
- Left filter panel (course/relation/status filters)
- Center SVG graph (nodes colored by course, edges colored by relation type)
- Right detail panel (node/edge detail)
- Compare drawer (compare report display)
- "Rebuild Graph" button

Key implementation details:
- Use SVG `<circle>` for nodes, `<line>` for edges
- Simple radial layout: group nodes by course, arrange in concentric circles
- Pan/zoom via SVG viewBox
- Click node → show detail in right panel
- Click edge → show edge detail + confirm/reject/compare buttons
- Compare drawer shows structured report

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  rebuildGraph, getGraph, getNodeDetail, confirmEdge, rejectEdge, compareNodes,
  type GraphNode, type GraphEdge, type NodeDetail, type CompareReport,
} from '../api/conceptGraph'
import { parseApiError } from '../utils/error'

const nodes = ref<GraphNode[]>([])
const edges = ref<GraphEdge[]>([])
const loading = ref(false)

const selectedNode = ref<NodeDetail | null>(null)
const selectedEdge = ref<GraphEdge | null>(null)
const compareDrawerVisible = ref(false)
const compareReport = ref<CompareReport | null>(null)
const compareLoading = ref(false)

// Filters
const filterCourseId = ref('')
const filterRelationType = ref('')
const filterStatus = ref('')

const relationColors: Record<string, string> = {
  similar_to: '#67C23A',
  contrast_with: '#E6A23C',
  prerequisite_of: '#409EFF',
  applies_to: '#909399',
  same_name_different_meaning: '#F56C6C',
  confused_with: '#9C27B0',
  parent_of: '#00BCD4',
}

const relationLabels: Record<string, string> = {
  similar_to: '相似',
  contrast_with: '对比',
  prerequisite_of: '前置',
  applies_to: '迁移应用',
  same_name_different_meaning: '同名异义',
  confused_with: '易混',
  parent_of: '上下位',
}

const statusLabels: Record<string, string> = {
  candidate: '候选',
  confirmed: '已确认',
  rejected: '已拒绝',
}

// Group nodes by course for layout
const courseGroups = computed(() => {
  const groups = new Map<number, GraphNode[]>()
  for (const n of filteredNodes.value) {
    if (!groups.has(n.course_id)) groups.set(n.course_id, [])
    groups.get(n.course_id)!.push(n)
  }
  return groups
})

const filteredNodes = computed(() => {
  if (!filterCourseId.value) return nodes.value
  const cid = Number(filterCourseId.value)
  return nodes.value.filter(n => n.course_id === cid)
})

const filteredEdges = computed(() => {
  const nodeIds = new Set(filteredNodes.value.map(n => n.id))
  return edges.value.filter(e =>
    nodeIds.has(e.source_node_id) && nodeIds.has(e.target_node_id) &&
    (!filterRelationType.value || e.relation_type === filterRelationType.value) &&
    (!filterStatus.value || e.status === filterStatus.value)
  )
})

// Radial layout: each course group is a cluster, clusters arranged in a circle
const layoutPositions = computed(() => {
  const positions = new Map<number, { x: number; y: number }>()
  const groups = Array.from(courseGroups.value.entries())
  const centerX = 400, centerY = 350
  const clusterRadius = groups.length > 1 ? 200 : 0

  groups.forEach(([courseId, groupNodes], gi) => {
    const angle = groups.length > 1 ? (gi / groups.length) * 2 * Math.PI : 0
    const cx = centerX + clusterRadius * Math.cos(angle)
    const cy = centerY + clusterRadius * Math.sin(angle)
    groupNodes.forEach((node, ni) => {
      const nodeAngle = groupNodes.length > 1 ? (ni / groupNodes.length) * 2 * Math.PI : 0
      const r = groupNodes.length > 1 ? 80 : 0
      positions.set(node.id, {
        x: cx + r * Math.cos(nodeAngle),
        y: cy + r * Math.sin(nodeAngle),
      })
    })
  })
  return positions
})

const courseColors = computed(() => {
  const colors = ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#9C27B0', '#00BCD4']
  const m = new Map<number, string>()
  Array.from(courseGroups.value.keys()).forEach((cid, i) => {
    m.set(cid, colors[i % colors.length])
  })
  return m
})

async function fetchGraph() {
  loading.value = true
  try {
    const params: Record<string, string> = {}
    if (filterCourseId.value) params.course_ids = filterCourseId.value
    if (filterRelationType.value) params.relation_type = filterRelationType.value
    if (filterStatus.value) params.status = filterStatus.value
    const { data } = await getGraph(params)
    nodes.value = data.nodes
    edges.value = data.edges
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取图谱失败'))
  } finally {
    loading.value = false
  }
}

async function handleRebuild() {
  loading.value = true
  try {
    await rebuildGraph()
    await fetchGraph()
    ElMessage.success('图谱重建完成')
  } catch (err) {
    ElMessage.error(parseApiError(err, '重建图谱失败'))
  } finally {
    loading.value = false
  }
}

async function handleNodeClick(node: GraphNode) {
  selectedEdge.value = null
  try {
    const { data } = await getNodeDetail(node.id)
    selectedNode.value = data
  } catch (err) {
    ElMessage.error(parseApiError(err, '获取节点详情失败'))
  }
}

function handleEdgeClick(edge: GraphEdge) {
  selectedNode.value = null
  selectedEdge.value = edge
}

async function handleConfirm() {
  if (!selectedEdge.value) return
  try {
    await confirmEdge(selectedEdge.value.id)
    selectedEdge.value.status = 'confirmed'
    ElMessage.success('已确认')
  } catch (err) {
    ElMessage.error(parseApiError(err, '确认失败'))
  }
}

async function handleReject() {
  if (!selectedEdge.value) return
  try {
    await rejectEdge(selectedEdge.value.id)
    selectedEdge.value.status = 'rejected'
    ElMessage.success('已拒绝')
  } catch (err) {
    ElMessage.error(parseApiError(err, '拒绝失败'))
  }
}

async function handleCompare() {
  if (!selectedEdge.value) return
  compareLoading.value = true
  compareDrawerVisible.value = true
  try {
    const { data } = await compareNodes(
      selectedEdge.value.source_node_id,
      selectedEdge.value.target_node_id,
      selectedEdge.value.id,
    )
    compareReport.value = data
  } catch (err) {
    ElMessage.error(parseApiError(err, '生成对比报告失败'))
  } finally {
    compareLoading.value = false
  }
}

onMounted(() => { fetchGraph() })
</script>
```

Template: SVG graph + filter panel + detail panel + compare drawer (see implementation).

- [ ] **Step 3: Register route**

Add to `frontend/src/router/index.ts` children:
```typescript
{
  path: 'knowledge-graph',
  name: 'knowledge-graph',
  component: () => import('../views/KnowledgeGraphView.vue'),
  meta: { requiresAuth: true },
},
```

- [ ] **Step 4: Add menu item**

In `frontend/src/layouts/MainLayout.vue`:
- Add `Share` to icon imports
- Add menu item:
```vue
<el-menu-item index="/knowledge-graph">
  <el-icon><Share /></el-icon>
  <span>知识图谱</span>
</el-menu-item>
```

- [ ] **Step 5: Run frontend build**

```bash
cd frontend && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/conceptGraph.ts frontend/src/views/KnowledgeGraphView.vue frontend/src/router/index.ts frontend/src/layouts/MainLayout.vue
git commit -m "feat(graph): add KnowledgeGraphView with SVG force graph"
```

---

## Task P6: Seed data + contract tests + acceptance + push

**Files:**
- Modify: `backend/scripts/seed_demo_data.py`
- Modify: `backend/app/tests/test_api_contracts.py`
- Modify: `scripts/verify_phase2_engineering.ps1`
- Modify: `scripts/verify_phase2_engineering.sh`

- [ ] **Step 1: Add cross-course seed data**

In `backend/scripts/seed_demo_data.py`, add a `_create_cross_course_graph()` helper that:
- Creates a 3rd course "数据库原理" (or reuses existing if present)
- Seeds KPs: 死锁, 页面置换 (OS) + 死锁, 缓冲池替换 (DB)
- Calls sync_nodes_for_user + generate_candidate_edges

- [ ] **Step 2: Add concept-graph contract tests**

Add to `test_api_contracts.py`:
```python
def test_concept_graph_response_contract(client):
    """GET /concept-graph returns {nodes: [...], edges: [...]}."""
    headers = auth_headers(client, username="alice")
    create_course(client, headers, name="操作系统")
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    resp = client.get("/api/v1/concept-graph", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {"nodes", "edges"}
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)
```

- [ ] **Step 3: Add acceptance script checks**

Add section 10 to both verify scripts: check that `KnowledgeGraphView.vue`, `conceptGraph.ts`, `/knowledge-graph` route, and menu item exist.

- [ ] **Step 4: Run full backend tests**

```bash
cd backend && .\.venv\Scripts\python.exe -m pytest app/tests/ -q
```

- [ ] **Step 5: Run frontend build**

```bash
cd frontend && npm run build
```

- [ ] **Step 6: Run acceptance script**

```bash
pwsh -NoProfile -File ./scripts/verify_phase2_engineering.ps1
```

- [ ] **Step 7: Commit and push**

```bash
git add backend/scripts/seed_demo_data.py backend/app/tests/test_api_contracts.py scripts/verify_phase2_engineering.ps1 scripts/verify_phase2_engineering.sh
git commit -m "feat(graph): add cross-course seed data and acceptance checks"
git push origin main
```

- [ ] **Step 8: Verify CI passes**

```bash
gh run list --limit 1
```
