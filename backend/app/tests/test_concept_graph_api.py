"""Concept graph API tests: rebuild, graph, node detail, confirm, reject.

KPs are seeded directly into the client's DB session (bypassing the
outline agent) so the tests are deterministic and fast.
"""
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.main import app
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.tests.conftest import auth_headers, create_course


def _seed_kps(client, kps: list[dict]) -> None:
    """Insert KPs directly into the client's DB session.

    Each kp dict has: course_id, title, summary, importance, source_chunk_ids.
    user_id is pulled from the course's owner.
    """
    db_gen = app.dependency_overrides[get_db]()
    db: Session = next(db_gen)
    try:
        for kp in kps:
            course = db.query(Course).filter_by(id=kp["course_id"]).first()
            user_id = course.user_id if course else 1
            db.add(
                KnowledgePoint(
                    user_id=user_id,
                    course_id=kp["course_id"],
                    title=kp["title"],
                    summary=kp["summary"],
                    importance=kp.get("importance", 3),
                    source_chunk_ids=kp.get("source_chunk_ids", "[]"),
                )
            )
        db.commit()
    finally:
        db.close()


def _setup_two_courses_with_kps(client, headers):
    """Create 2 courses with overlapping-title KPs. Returns (os_id, db_id)."""
    os_id = create_course(client, headers, name="操作系统")
    db_id = create_course(client, headers, name="数据库")
    _seed_kps(
        client,
        [
            {
                "course_id": os_id,
                "title": "死锁",
                "summary": "资源循环等待",
                "importance": 5,
            },
            {
                "course_id": os_id,
                "title": "页面置换",
                "summary": "有限内存下的页面淘汰",
                "importance": 4,
            },
            {
                "course_id": db_id,
                "title": "死锁",
                "summary": "事务锁冲突",
                "importance": 5,
            },
            {
                "course_id": db_id,
                "title": "缓冲池替换",
                "summary": "有限缓存下的页面淘汰",
                "importance": 4,
            },
        ],
    )
    return os_id, db_id


def test_rebuild_graph(client):
    """POST /concept-graph/rebuild syncs nodes and generates edges."""
    headers = auth_headers(client, username="alice")
    _setup_two_courses_with_kps(client, headers)
    resp = client.post("/api/v1/concept-graph/rebuild", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "nodes_count" in body
    assert "edges_count" in body
    assert body["nodes_count"] == 4
    assert body["edges_count"] >= 1


def test_get_graph(client):
    """GET /concept-graph returns nodes + edges."""
    headers = auth_headers(client, username="alice")
    _setup_two_courses_with_kps(client, headers)
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    resp = client.get("/api/v1/concept-graph", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "nodes" in body and "edges" in body
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)
    assert len(body["nodes"]) == 4
    assert len(body["edges"]) >= 1


def test_get_node_detail(client):
    """GET /concept-graph/nodes/{id} returns node detail with edges."""
    headers = auth_headers(client, username="alice")
    _setup_two_courses_with_kps(client, headers)
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    graph = client.get("/api/v1/concept-graph", headers=headers).json()
    assert graph["nodes"], "expected at least one node after rebuild"
    node_id = graph["nodes"][0]["id"]
    resp = client.get(
        f"/api/v1/concept-graph/nodes/{node_id}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "id" in body and "title" in body
    assert "related_edges" in body
    assert isinstance(body["related_edges"], list)


def test_confirm_edge(client):
    """POST /concept-graph/edges/{id}/confirm changes status."""
    headers = auth_headers(client, username="alice")
    _setup_two_courses_with_kps(client, headers)
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    graph = client.get("/api/v1/concept-graph", headers=headers).json()
    assert graph["edges"], "expected at least one candidate edge"
    edge_id = graph["edges"][0]["id"]
    resp = client.post(
        f"/api/v1/concept-graph/edges/{edge_id}/confirm", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "confirmed"


def test_reject_edge(client):
    """POST /concept-graph/edges/{id}/reject changes status."""
    headers = auth_headers(client, username="alice")
    _setup_two_courses_with_kps(client, headers)
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    graph = client.get("/api/v1/concept-graph", headers=headers).json()
    assert graph["edges"], "expected at least one candidate edge"
    edge_id = graph["edges"][0]["id"]
    resp = client.post(
        f"/api/v1/concept-graph/edges/{edge_id}/reject", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"
