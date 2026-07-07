"""Concept graph service tests: node sync, candidate edges, confirm/reject."""
from app.models import (
    Course,
    ConceptEdge,
    ConceptNode,
    KnowledgePoint,
    User,
)
from app.services.concept_graph_service import (
    confirm_edge,
    generate_candidate_edges,
    get_graph,
    reject_edge,
    sync_nodes_for_user,
)


def _setup_two_courses(db_session):
    """Create user + 2 courses + KPs with overlapping titles."""
    user = User(username="alice", email="a@x.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    os_course = Course(name="操作系统", user_id=user.id)
    db_course = Course(name="数据库", user_id=user.id)
    db_session.add_all([os_course, db_course])
    db_session.commit()

    # OS knowledge points
    os_kp1 = KnowledgePoint(
        user_id=user.id,
        course_id=os_course.id,
        title="死锁",
        summary="资源循环等待",
        importance=5,
        source_chunk_ids="[]",
    )
    os_kp2 = KnowledgePoint(
        user_id=user.id,
        course_id=os_course.id,
        title="页面置换",
        summary="有限内存下的页面淘汰",
        importance=4,
        source_chunk_ids="[]",
    )
    # DB knowledge points
    db_kp1 = KnowledgePoint(
        user_id=user.id,
        course_id=db_course.id,
        title="死锁",
        summary="事务锁冲突",
        importance=5,
        source_chunk_ids="[]",
    )
    db_kp2 = KnowledgePoint(
        user_id=user.id,
        course_id=db_course.id,
        title="缓冲池替换",
        summary="有限缓存下的页面淘汰",
        importance=4,
        source_chunk_ids="[]",
    )
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
    deadlock_edges = [
        e for e in edges if e.relation_type == "same_name_different_meaning"
    ]
    assert len(deadlock_edges) >= 1
    assert all(e.confidence >= 0.45 for e in deadlock_edges)


def test_candidate_edges_similar_to(db_session):
    user, os_course, db_course = _setup_two_courses(db_session)
    sync_nodes_for_user(db_session, user.id)
    generate_candidate_edges(db_session, user.id)
    edges = db_session.query(ConceptEdge).filter_by(user_id=user.id).all()
    # 页面置换 ↔ 缓冲池替换: both summaries share "页面淘汰" → similar_to / applies_to
    similar_edges = [
        e for e in edges
        if e.relation_type in ("similar_to", "applies_to")
    ]
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
    edges_before = (
        db_session.query(ConceptEdge).filter_by(user_id=user.id).count()
    )
    edge = db_session.query(ConceptEdge).filter_by(user_id=user.id).first()
    reject_edge(db_session, user.id, edge.id)
    generate_candidate_edges(db_session, user.id)
    edges_after = (
        db_session.query(ConceptEdge).filter_by(user_id=user.id).count()
    )
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
