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
