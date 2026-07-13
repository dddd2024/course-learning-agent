"""V7.4.3-04 regressions for truthful task verification responses."""
from __future__ import annotations

from app.tests.test_v7_4_2_quiz_atomic import _setup_quiz_with_task


def test_failing_quiz_submission_reports_real_task_verification(client):
    quiz_id, item_id, task_id, headers = _setup_quiz_with_task(client, "v743_atomic_fail")
    response = client.post(
        f"/api/v1/quizzes/{quiz_id}/submit",
        json={"answers": [{"item_id": item_id, "user_answer": "false"}], "task_id": task_id},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["passed"] is False
    assert result["task_verification"]["verified"] is False
    assert result["task_verification"]["execution_status"] == "in_progress"
