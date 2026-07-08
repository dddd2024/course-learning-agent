"""End-to-end learning flow test.

Covers the full learning-assistant flow as an API-level E2E test
(no browser/Playwright): login → create course → upload material →
parse → create conversation → ask question → single-course plan →
multi-course plan. Runs against the in-memory test DB with the mock
LLM provider, so it is deterministic and fast.
"""
from app.tests.conftest import auth_headers, create_course


def test_full_learning_flow(client) -> None:
    """完整学习助手流程：登录→建课→上传→解析→提问→单课程计划→多课程计划。"""
    headers = auth_headers(client, username="e2e_user")

    # 1. 创建两门课程
    os_course_id = create_course(client, headers, name="操作系统")
    db_course_id = create_course(client, headers, name="数据库")

    # 2. 上传操作系统资料（最小 txt 内容）
    upload_resp = client.post(
        f"/api/v1/courses/{os_course_id}/materials",
        headers=headers,
        files={
            "file": (
                "note.txt",
                "进程是程序在数据集合上运行的过程\n线程是进程内的执行单元\n".encode(
                    "utf-8"
                ),
                "text/plain",
            )
        },
    )
    assert upload_resp.status_code == 201, upload_resp.text
    material_id = upload_resp.json()["id"]

    # 3. 解析资料（后台任务，立即返回 processing）
    parse_resp = client.post(
        f"/api/v1/materials/{material_id}/parse", headers=headers
    )
    assert parse_resp.status_code == 200, parse_resp.text
    # Background task: endpoint returns processing immediately.
    assert parse_resp.json()["status"] == "processing"
    # Verify the background task completed and material is ready.
    mat_resp = client.get(
        f"/api/v1/courses/{os_course_id}/materials", headers=headers
    )
    mat_row = next(
        m for m in mat_resp.json()["items"] if m["id"] == material_id
    )
    assert mat_row["status"] == "ready"

    # 4. 创建对话并提问
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": os_course_id, "title": "E2E 测试对话"},
        headers=headers,
    )
    assert conv_resp.status_code in (200, 201), conv_resp.text
    conversation_id = conv_resp.json()["id"]

    chat_resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": os_course_id,
            "conversation_id": conversation_id,
            "question": "什么是进程？",
        },
        headers=headers,
    )
    assert chat_resp.status_code == 200, chat_resp.text
    chat_body = chat_resp.json()
    assert "answer" in chat_body
    assert isinstance(chat_body["answer"], str)

    # 5. 生成单课程计划
    plan_resp = client.post(
        "/api/v1/plans",
        json={
            "goal": "掌握操作系统",
            "courses": ["操作系统"],
            "deadline": "2099-01-01",
            "daily_minutes": 120,
        },
        headers=headers,
    )
    assert plan_resp.status_code == 200, plan_resp.text
    plan_body = plan_resp.json()
    assert "goal" in plan_body
    assert "tasks" in plan_body

    # 6. 生成多课程计划
    multi_resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [
                {"course_id": os_course_id, "deadline": "2099-01-01"},
                {"course_id": db_course_id, "deadline": "2099-01-01"},
            ],
            "daily_minutes": 120,
        },
        headers=headers,
    )
    assert multi_resp.status_code == 200, multi_resp.text
    multi_body = multi_resp.json()
    assert "schedule" in multi_body
    assert "overflow_warnings" in multi_body
