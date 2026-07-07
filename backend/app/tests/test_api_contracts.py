"""API contract tests — lock the response shape of core endpoints.

These tests do NOT assert business logic correctness; they only assert
that the response structure (field names, types, nesting) stays stable
so frontend/backend refactors cannot silently break the contract.

If a contract intentionally changes, update BOTH the test and the
frontend TypeScript types in the same commit.
"""
from app.tests.conftest import (
    auth_headers,
    create_course,
    upload_material,
)


# ---------------------------------------------------------------------------
# Multi-course plan contract
# ---------------------------------------------------------------------------


def test_multi_plan_response_contract(client) -> None:
    """POST /plans/multi 返回 {schedule: [...], overflow_warnings: [...]}。"""
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="契约课程")
    resp = client.post(
        "/api/v1/plans/multi",
        json={
            "courses": [{"course_id": course_id, "deadline": "2099-01-01"}],
            "daily_minutes": 120,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 顶层字段
    assert set(body.keys()) >= {"schedule", "overflow_warnings"}
    assert isinstance(body["schedule"], list)
    assert isinstance(body["overflow_warnings"], list)
    # schedule 每项的字段
    for item in body["schedule"]:
        assert set(item.keys()) >= {
            "scheduled_date",
            "course_name",
            "title",
            "estimate_minutes",
            "start_time",
            "end_time",
        }


# ---------------------------------------------------------------------------
# Chat response contract
# ---------------------------------------------------------------------------


def test_chat_response_contract(client) -> None:
    """POST /chat 返回稳定字段：message_id/answer/citations/not_found/...。"""
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="聊天契约课程")
    # 上传并解析一份资料，确保 chat 有上下文
    material_id = upload_material(
        client,
        headers,
        course_id,
        "note.txt",
        "进程是程序在数据集合上运行的过程\n".encode("utf-8"),
    )
    client.post(f"/api/v1/materials/{material_id}/parse", headers=headers)

    # 创建对话
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "契约测试对话"},
        headers=headers,
    )
    assert conv_resp.status_code in (200, 201), conv_resp.text
    conversation_id = conv_resp.json()["id"]

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是进程？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 必填字段
    assert set(body.keys()) >= {
        "message_id",
        "answer",
        "citations",
        "not_found",
        "follow_up_questions",
        "retrieved_chunks",
        "fallback_used",
        "fallback_reason",
    }
    assert isinstance(body["message_id"], int)
    assert isinstance(body["answer"], str)
    assert isinstance(body["citations"], list)
    assert isinstance(body["not_found"], bool)
    assert isinstance(body["follow_up_questions"], list)
    assert isinstance(body["retrieved_chunks"], list)
    assert isinstance(body["fallback_used"], bool)


# ---------------------------------------------------------------------------
# Material upload + parse contract
# ---------------------------------------------------------------------------


def test_material_upload_contract(client) -> None:
    """POST /courses/{id}/materials 返回 MaterialResponse（含 id/filename/status）。"""
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="上传契约课程")
    resp = client.post(
        f"/api/v1/courses/{course_id}/materials",
        headers=headers,
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body.keys()) >= {
        "id",
        "filename",
        "file_type",
        "status",
        "version",
        "course_id",
    }
    assert body["status"] == "uploaded"
    assert body["version"] == 1


def test_material_parse_contract(client) -> None:
    """POST /materials/{id}/parse 返回 {material_id, status, chunk_count}。"""
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="解析契约课程")
    material_id = upload_material(
        client, headers, course_id, "note.txt", "进程是程序运行的过程\n".encode("utf-8")
    )
    resp = client.post(f"/api/v1/materials/{material_id}/parse", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) >= {"material_id", "status", "chunk_count"}
    assert body["status"] == "ready"
    assert isinstance(body["chunk_count"], int)


def test_material_list_contract(client) -> None:
    """GET /courses/{id}/materials 返回 {items: [...], total: int}。"""
    headers = auth_headers(client, username="alice")
    course_id = create_course(client, headers, name="列表契约课程")
    upload_material(client, headers, course_id, "a.txt", b"aaa")
    resp = client.get(f"/api/v1/courses/{course_id}/materials", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) >= {"items", "total"}
    assert isinstance(body["items"], list)
    assert isinstance(body["total"], int)


# ---------------------------------------------------------------------------
# Error response contract
# ---------------------------------------------------------------------------


def test_not_found_error_contract(client) -> None:
    """404 错误返回 {code: 'NOT_FOUND', message: str}（非 FastAPI 默认 detail）。"""
    headers = auth_headers(client, username="alice")
    resp = client.get("/api/v1/courses/999999/materials", headers=headers)
    assert resp.status_code == 404
    body = resp.json()
    assert set(body.keys()) >= {"code", "message"}
    assert body["code"] == "NOT_FOUND"
    assert isinstance(body["message"], str)
    assert "detail" not in body  # 不应使用 FastAPI 默认的 detail 字段
