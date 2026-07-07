"""ConceptNode / ConceptEdge / ConceptCompareReport model tests."""
from app.models import (
    ConceptCompareReport,
    ConceptEdge,
    ConceptNode,
)


def test_concept_node_fields(db_session, sample_user, sample_course):
    """ConceptNode persists all fields and gets auto id + timestamps."""
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
    assert node.importance == 5


def test_concept_edge_fields(db_session, sample_user, sample_course):
    """ConceptEdge persists with default status=candidate."""
    n1 = ConceptNode(
        user_id=sample_user.id,
        course_id=sample_course.id,
        title="A",
        normalized_title="a",
    )
    n2 = ConceptNode(
        user_id=sample_user.id,
        course_id=sample_course.id,
        title="B",
        normalized_title="b",
    )
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
    assert edge.confidence == 0.8


def test_concept_compare_report_fields(db_session, sample_user, sample_course):
    """ConceptCompareReport persists structured report data."""
    n1 = ConceptNode(
        user_id=sample_user.id,
        course_id=sample_course.id,
        title="A",
        normalized_title="a",
    )
    n2 = ConceptNode(
        user_id=sample_user.id,
        course_id=sample_course.id,
        title="B",
        normalized_title="b",
    )
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
    assert report.provider == "mock"
    assert report.report_json == '{"similarities": []}'


def test_concept_edge_default_status(db_session, sample_user, sample_course):
    """ConceptEdge defaults to status='candidate' when not specified."""
    n1 = ConceptNode(
        user_id=sample_user.id,
        course_id=sample_course.id,
        title="A",
        normalized_title="a",
    )
    n2 = ConceptNode(
        user_id=sample_user.id,
        course_id=sample_course.id,
        title="B",
        normalized_title="b",
    )
    db_session.add_all([n1, n2])
    db_session.commit()

    edge = ConceptEdge(
        user_id=sample_user.id,
        source_node_id=n1.id,
        target_node_id=n2.id,
        relation_type="similar_to",
        confidence=0.5,
    )
    db_session.add(edge)
    db_session.commit()
    # SQLite default applies on INSERT when column not set
    db_session.refresh(edge)
    assert edge.status == "candidate"
