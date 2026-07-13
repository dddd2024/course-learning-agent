from app.agents.outline import _reconcile_chunk_ids
from app.services.task_target_resolver import resolve_target
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material

def test_invalid_source_never_falls_back_to_all_chunks():
    assert _reconcile_chunk_ids([999], [1, 2, 3]) == []

def test_chinese_target_matching_is_explainable(db_session, sample_user, sample_course):
    point = KnowledgePoint(user_id=sample_user.id, course_id=sample_course.id, title="信号量机制", status="active", source_chunk_ids="[1]")
    db_session.add(point); db_session.commit()
    kind, target_id, spec = resolve_target(db_session, sample_course.id, "review", "复习进程同步与信号量")
    assert kind == "knowledge_point" and target_id == point.id and spec["resolution_status"] == "resolved"


def test_generic_learn_step_resolves_the_only_ready_material(db_session, sample_user, sample_course):
    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="任意命名的课程资料.txt",
        file_type="txt",
        file_path="fixture.txt",
        status="ready",
    )
    db_session.add(material)
    db_session.commit()

    kind, target_id, spec = resolve_target(db_session, sample_course.id, "learn", "学习课程资料")

    assert kind == "material"
    assert target_id == material.id
    assert spec["resolution_status"] == "resolved"


def test_generic_learn_step_does_not_guess_between_multiple_materials(db_session, sample_user, sample_course):
    for filename in ("网络基础.txt", "操作系统导论.txt"):
        db_session.add(Material(
            user_id=sample_user.id,
            course_id=sample_course.id,
            filename=filename,
            file_type="txt",
            file_path=filename,
            status="ready",
        ))
    db_session.commit()

    kind, target_id, spec = resolve_target(db_session, sample_course.id, "learn", "学习课程资料")

    assert kind == "material"
    assert target_id is None
    assert spec["resolution_status"] == "unresolved"
