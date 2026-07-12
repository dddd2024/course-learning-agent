from app.models.material import Material
from app.models.parse_job import ParseJob
from app.services.parse_job_service import create_or_get_job, recover_stale_jobs
from app.core.timezone import utc_now
from datetime import timedelta


def test_parse_job_is_idempotent_and_stale_job_recovers(db_session, sample_user, sample_course):
    material = Material(user_id=sample_user.id, course_id=sample_course.id, filename="a.txt", file_type="txt", file_path="x", status="uploaded")
    db_session.add(material); db_session.commit()
    first = create_or_get_job(db_session, material, sample_user.id)
    second = create_or_get_job(db_session, material, sample_user.id)
    assert first.id == second.id and first.status == "queued"
    first.status, first.heartbeat_at = "running", utc_now() - timedelta(seconds=601)
    db_session.commit()
    assert recover_stale_jobs(db_session) == 1
    # V6-50: stale running jobs are re-queued (not failed) so the
    # persistent worker can pick them up again.
    assert db_session.get(ParseJob, first.id).status == "queued"
