"""Concept compare agent + service tests."""
from app.models import (
    ConceptCompareReport,
    ConceptNode,
    Course,
    User,
)
from app.services.concept_compare_service import get_or_create_compare_report


def _setup_two_nodes(db_session):
    """Create user + 2 courses + 2 ConceptNodes with the same title."""
    user = User(username="alice", email="a@x.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    c1 = Course(name="操作系统", user_id=user.id)
    c2 = Course(name="数据库", user_id=user.id)
    db_session.add_all([c1, c2])
    db_session.commit()
    n1 = ConceptNode(
        user_id=user.id,
        course_id=c1.id,
        title="死锁",
        normalized_title="死锁",
        summary="资源循环等待",
    )
    n2 = ConceptNode(
        user_id=user.id,
        course_id=c2.id,
        title="死锁",
        normalized_title="死锁",
        summary="事务锁冲突",
    )
    db_session.add_all([n1, n2])
    db_session.commit()
    return user, n1, n2


def test_compare_creates_report(db_session):
    user, n1, n2 = _setup_two_nodes(db_session)
    result = get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id
    )
    assert result is not None
    assert "report_json" in result
    report = db_session.query(ConceptCompareReport).first()
    assert report is not None
    assert report.provider in ("mock", "real", "user")


def test_compare_report_has_required_fields(db_session):
    user, n1, n2 = _setup_two_nodes(db_session)
    result = get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id
    )
    rj = result["report_json"]
    assert "concept_a" in rj or "similarities" in rj
    assert "differences" in rj or "concept_b" in rj


def test_compare_is_cached(db_session):
    user, n1, n2 = _setup_two_nodes(db_session)
    get_or_create_compare_report(db_session, user.id, n1.id, n2.id)
    get_or_create_compare_report(db_session, user.id, n1.id, n2.id)
    reports = db_session.query(ConceptCompareReport).all()
    assert len(reports) == 1


def test_compare_nonexistent_node_returns_none(db_session):
    user, _, _ = _setup_two_nodes(db_session)
    result = get_or_create_compare_report(
        db_session, user.id, 999, 998
    )
    assert result is None


def test_compare_is_cached_reverse_order(db_session):
    """Caching should match (a,b) and (b,a) as the same pair."""
    user, n1, n2 = _setup_two_nodes(db_session)
    get_or_create_compare_report(db_session, user.id, n1.id, n2.id)
    get_or_create_compare_report(db_session, user.id, n2.id, n1.id)
    reports = db_session.query(ConceptCompareReport).all()
    assert len(reports) == 1


def test_compare_uses_evidence_chunks(db_session, monkeypatch):
    """compare service 应从 node/edge 的 chunk ids 加载 MaterialChunk 文本。"""
    import json
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
    for c in captured["evidence_chunks"]:
        assert "text" in c


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


def test_compare_rejects_foreign_edge_id(db_session):
    """edge_id 属于他人时返回 None（endpoint 层转 404）。"""
    from app.models import ConceptEdge

    user, n1, n2 = _setup_two_nodes(db_session)
    other = User(username="bob", email="b@x.com", password_hash="x")
    db_session.add(other)
    db_session.commit()
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
    result = get_or_create_compare_report(
        db_session, user.id, n1.id, n2.id, edge_id=mismatch_edge.id
    )
    assert result is None
