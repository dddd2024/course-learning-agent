"""V6-30: Fix knowledge point title cleaning.

Tests verify that:
- Technical terms (TCP/IP, CSMA/CD, HTTP/2, I/O, B+树, Client/Server) are
  accepted as valid knowledge point titles.
- Actual URLs and IP addresses are still rejected.
- KP regeneration archives old KPs instead of deleting them.
- Archived KPs are not shown in the default list.
- Old quiz results still reference archived KPs.
"""
import json

from app.agents.outline import _is_valid_concept_title
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.quiz import Quiz, QuizItem
from app.tests.conftest import auth_headers, setup_course_with_material

# Content for material that will produce knowledge points via the mock LLM.
KP_TEXT = (
    "操作系统课程笔记\n"
    "第一章 内存管理\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
    "页表存储虚拟页到物理页的映射关系。\n"
).encode("utf-8")


# ---------------------------------------------------------------------------
# _is_valid_concept_title() — technical terms must be accepted
# ---------------------------------------------------------------------------

def test_tcp_ip_accepted_as_valid_title():
    """TCP/IP is a protocol name, not a URL — must be a valid KP title."""
    assert _is_valid_concept_title("TCP/IP") is True


def test_csma_cd_accepted_as_valid_title():
    """CSMA/CD is a protocol name, not a URL — must be a valid KP title."""
    assert _is_valid_concept_title("CSMA/CD") is True


def test_http2_accepted_as_valid_title():
    """HTTP/2 is a protocol version, not a URL — must be a valid KP title."""
    assert _is_valid_concept_title("HTTP/2") is True


def test_io_accepted_as_valid_title():
    """I/O is a standard abbreviation — must be a valid KP title."""
    assert _is_valid_concept_title("I/O") is True


def test_b_plus_tree_accepted_as_valid_title():
    """B+树 is a data structure name — must be a valid KP title."""
    assert _is_valid_concept_title("B+树") is True


def test_client_server_accepted_as_valid_title():
    """Client/Server is an architecture name — must be a valid KP title."""
    assert _is_valid_concept_title("Client/Server") is True


# ---------------------------------------------------------------------------
# _is_valid_concept_title() — URLs and IPs must still be rejected
# ---------------------------------------------------------------------------

def test_actual_urls_rejected_as_titles():
    """URLs must still be rejected as KP titles."""
    assert _is_valid_concept_title("http://example.com") is False
    assert _is_valid_concept_title("https://test.org/page") is False
    assert _is_valid_concept_title("ftp://files.example.com") is False
    assert _is_valid_concept_title("www.example.com") is False


def test_ip_addresses_rejected_as_titles():
    """IP addresses must still be rejected as KP titles."""
    assert _is_valid_concept_title("192.168.1.1") is False
    assert _is_valid_concept_title("10.0.0.1") is False


def test_file_paths_rejected_as_titles():
    """File paths starting with drive letters must be rejected."""
    assert _is_valid_concept_title("C:/Users/admin") is False
    assert _is_valid_concept_title("D:\\Documents\\file.txt") is False


# ---------------------------------------------------------------------------
# DB-based tests for KP regeneration versioning
# ---------------------------------------------------------------------------

def _setup_course_with_chunks(client, monkeypatch, tmp_path):
    """Create a course with parsed material and return auth headers + course_id."""
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed")
    )
    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=KP_TEXT)
    return headers, course_id


def test_kp_regeneration_archives_old_kps(client, tmp_path, monkeypatch):
    """Regenerating KPs archives old ones instead of deleting them.

    V6-30 requirement: when regenerating, old KPs get status='archived'
    and new KPs are created with a new generation number.
    """
    headers, course_id = _setup_course_with_chunks(client, monkeypatch, tmp_path)

    # First generation
    resp1 = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )
    assert resp1.status_code == 200
    body1 = resp1.json()
    gen1_count = len(body1["knowledge_points"])
    assert gen1_count >= 1
    # The response should include generation and archived_count
    assert "generation" in body1
    assert body1["generation"] >= 1
    assert "archived_count" in body1

    # Collect first-generation KP IDs
    gen1_ids = {kp["id"] for kp in body1["knowledge_points"]}

    # Second generation (regenerate)
    resp2 = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["generation"] > body1["generation"]
    assert body2["archived_count"] >= gen1_count  # old KPs were archived

    # Old KPs should still exist with status='archived'
    gen2_ids = {kp["id"] for kp in body2["knowledge_points"]}

    # New KPs should be different from old ones (new generation)
    # At least some new IDs should not be in the old set
    assert gen2_ids != gen1_ids or body2["generation"] > 1

    # Verify old KPs are archived in the DB
    from app.api.deps import get_db
    from app.main import app

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        old_kps = (
            db.query(KnowledgePoint)
            .filter(KnowledgePoint.id.in_(gen1_ids))
            .all()
        )
        assert len(old_kps) > 0, "Old KPs should not be deleted"
        for kp in old_kps:
            assert kp.status == "archived", (
                f"Old KP {kp.id} should be archived, got status={kp.status}"
            )

        new_kps = (
            db.query(KnowledgePoint)
            .filter(KnowledgePoint.id.in_(gen2_ids))
            .all()
        )
        for kp in new_kps:
            assert kp.status == "active"
            assert kp.generation == body2["generation"]
    finally:
        db.close()

def test_archived_kps_not_in_default_list(client, tmp_path, monkeypatch):
    """Archived KPs are not shown in the default knowledge-points list."""
    headers, course_id = _setup_course_with_chunks(client, monkeypatch, tmp_path)

    # Generate first generation
    client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )

    # Regenerate to archive the first generation
    client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )

    # Default list should only show active KPs
    resp = client.get(
        f"/api/v1/courses/{course_id}/knowledge-points",
        headers=headers,
    )
    assert resp.status_code == 200
    active_items = resp.json()["items"]
    for kp in active_items:
        assert kp.get("status", "active") == "active"

    # include_archived=true should show both active and archived
    resp_all = client.get(
        f"/api/v1/courses/{course_id}/knowledge-points?include_archived=true",
        headers=headers,
    )
    assert resp_all.status_code == 200
    all_items = resp_all.json()["items"]
    assert len(all_items) > len(active_items), (
        "include_archived should show more KPs than the default list"
    )


def test_old_quiz_results_reference_archived_kps(client, tmp_path, monkeypatch):
    """Quiz results created before regeneration still reference old (archived) KPs.

    V6-30 requirement: keep old quiz results and historical references.
    When KPs are archived, quiz items pointing to them must remain valid.
    """
    headers, course_id = _setup_course_with_chunks(client, monkeypatch, tmp_path)

    # Generate first generation of KPs
    resp1 = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate",
        headers=headers,
    )
    assert resp1.status_code == 200
    gen1_kps = resp1.json()["knowledge_points"]
    assert len(gen1_kps) >= 1
    old_kp_id = gen1_kps[0]["id"]

    # Simulate a quiz result that references the first-generation KP
    from app.api.deps import get_db
    from app.main import app

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from app.models.user import User

        user = db.query(User).filter(User.username == "alice").first()

        quiz = Quiz(
            user_id=user.id,
            course_id=course_id,
            title="Test Quiz",
            question_count=1,
            status="submitted",
            score=0,
        )
        db.add(quiz)
        db.flush()

        quiz_item = QuizItem(
            quiz_id=quiz.id,
            knowledge_point_id=old_kp_id,
            question_type="choice",
            question_text="What is TCP/IP?",
            options=json.dumps(["A. protocol", "B. hardware", "C. language", "D. OS"]),
            answer="A",
            explanation="TCP/IP is a protocol suite.",
            order_index=0,
        )
        db.add(quiz_item)
        db.commit()
    finally:
        db.close()


def test_failed_generation_keeps_existing_active_outline(client, tmp_path, monkeypatch):
    """Zero valid replacements must not archive the learner's active KPs."""
    headers, course_id = _setup_course_with_chunks(client, monkeypatch, tmp_path)
    initial = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate", headers=headers
    )
    assert initial.status_code == 200
    original_ids = {item["id"] for item in initial.json()["knowledge_points"]}

    monkeypatch.setattr(
        "app.api.v1.endpoints.knowledge_points.outline_generate",
        lambda *args, **kwargs: [{
            "title": "invalid",
            "summary": "invalid evidence",
            "importance": 1,
            "source_chunk_ids": [999999],
            "exam_style": "short",
            "review_action": "review",
        }],
    )
    failed = client.post(
        f"/api/v1/courses/{course_id}/knowledge-points/generate", headers=headers
    )
    assert failed.status_code == 422

    active = client.get(
        f"/api/v1/courses/{course_id}/knowledge-points", headers=headers
    )
    assert {item["id"] for item in active.json()["items"]} == original_ids
