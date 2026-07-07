"""Concept graph permission tests: user isolation."""
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.main import app
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.tests.conftest import auth_headers, create_course


def _seed_kp_for_course(client, course_id: int, title: str, summary: str) -> None:
    """Insert one KP for a course, pulling user_id from course owner."""
    db_gen = app.dependency_overrides[get_db]()
    db: Session = next(db_gen)
    try:
        course = db.query(Course).filter_by(id=course_id).first()
        user_id = course.user_id if course else 1
        db.add(
            KnowledgePoint(
                user_id=user_id,
                course_id=course_id,
                title=title,
                summary=summary,
                importance=3,
                source_chunk_ids="[]",
            )
        )
        db.commit()
    finally:
        db.close()


def test_other_user_cannot_access_graph(client):
    """Alice's graph is invisible to Bob."""
    headers_a = auth_headers(client, username="alice", email="a@x.com")
    headers_b = auth_headers(client, username="bob", email="b@x.com")
    os_id = create_course(client, headers_a, name="操作系统")
    db_id = create_course(client, headers_a, name="数据库")
    _seed_kp_for_course(client, os_id, "死锁", "资源循环等待")
    _seed_kp_for_course(client, db_id, "死锁", "事务锁冲突")
    client.post("/api/v1/concept-graph/rebuild", headers=headers_a)
    # Bob sees empty graph
    resp = client.get("/api/v1/concept-graph", headers=headers_b)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) == 0
    assert len(body["edges"]) == 0


def test_other_user_cannot_confirm_edge(client):
    """Bob cannot confirm Alice's edge (404)."""
    headers_a = auth_headers(client, username="alice", email="a@x.com")
    headers_b = auth_headers(client, username="bob", email="b@x.com")
    os_id = create_course(client, headers_a, name="操作系统")
    db_id = create_course(client, headers_a, name="数据库")
    _seed_kp_for_course(client, os_id, "死锁", "资源循环等待")
    _seed_kp_for_course(client, db_id, "死锁", "事务锁冲突")
    client.post("/api/v1/concept-graph/rebuild", headers=headers_a)
    graph = client.get("/api/v1/concept-graph", headers=headers_a).json()
    assert graph["edges"], "Alice should have at least one candidate edge"
    edge_id = graph["edges"][0]["id"]
    resp = client.post(
        f"/api/v1/concept-graph/edges/{edge_id}/confirm", headers=headers_b
    )
    assert resp.status_code == 404


def test_other_user_node_detail_404(client):
    """Bob cannot read Alice's node detail (404)."""
    headers_a = auth_headers(client, username="alice", email="a@x.com")
    headers_b = auth_headers(client, username="bob", email="b@x.com")
    os_id = create_course(client, headers_a, name="操作系统")
    db_id = create_course(client, headers_a, name="数据库")
    _seed_kp_for_course(client, os_id, "死锁", "资源循环等待")
    _seed_kp_for_course(client, db_id, "死锁", "事务锁冲突")
    client.post("/api/v1/concept-graph/rebuild", headers=headers_a)
    graph = client.get("/api/v1/concept-graph", headers=headers_a).json()
    assert graph["nodes"], "Alice should have at least one node"
    node_id = graph["nodes"][0]["id"]
    resp = client.get(
        f"/api/v1/concept-graph/nodes/{node_id}", headers=headers_b
    )
    assert resp.status_code == 404
