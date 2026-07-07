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


# ---------------------------------------------------------------------------
# Agent audit (agent-runs) contract
# ---------------------------------------------------------------------------


def _create_chat_run(client, headers, course_name: str, question: str) -> int:
    """辅助：创建课程→上传→解析→对话→提问，返回产生的第一个 AgentRun id。"""
    course_id = create_course(client, headers, name=course_name)
    material_id = upload_material(
        client,
        headers,
        course_id,
        "note.txt",
        f"{question}的答案是示例文本\n".encode("utf-8"),
    )
    client.post(f"/api/v1/materials/{material_id}/parse", headers=headers)
    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": f"{course_name} 对话"},
        headers=headers,
    )
    conversation_id = conv_resp.json()["id"]
    client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": question,
        },
        headers=headers,
    )
    list_resp = client.get("/api/v1/agent-runs", headers=headers)
    return list_resp.json()["items"][0]["id"]


def test_agent_runs_list_contract(client) -> None:
    """GET /agent-runs 返回 {items: [...], total: int}。"""
    headers = auth_headers(client, username="alice")
    _create_chat_run(client, headers, "审计契约课程", "什么是进程？")

    resp = client.get("/api/v1/agent-runs", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) >= {"items", "total"}
    assert isinstance(body["items"], list)
    assert isinstance(body["total"], int)
    assert body["total"] >= 1
    for item in body["items"]:
        assert set(item.keys()) >= {
            "id",
            "user_id",
            "run_type",
            "status",
            "input_summary",
            "output_summary",
            "duration_ms",
        }


def test_agent_runs_detail_contract(client) -> None:
    """GET /agent-runs/{id} 返回含 steps 的详情，step 有 input_data/output_data。"""
    headers = auth_headers(client, username="alice")
    run_id = _create_chat_run(client, headers, "审计详情课程", "什么是线程？")

    resp = client.get(f"/api/v1/agent-runs/{run_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) >= {"id", "run_type", "status", "steps"}
    assert isinstance(body["steps"], list)
    for step in body["steps"]:
        assert set(step.keys()) >= {
            "id",
            "run_id",
            "step_name",
            "step_index",
            "input_data",
            "output_data",
            "status",
        }


def test_agent_runs_isolation_contract(client) -> None:
    """非本人 run 访问返回 404（不泄漏存在性）。"""
    headers_a = auth_headers(client, username="alice", email="a@x.com")
    headers_b = auth_headers(client, username="bob", email="b@x.com")

    run_id = _create_chat_run(client, headers_a, "隔离课程", "什么是进程？")

    # bob 不能访问 alice 的 run
    resp = client.get(f"/api/v1/agent-runs/{run_id}", headers=headers_b)
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "NOT_FOUND"


def test_agent_runs_retrieve_step_items_contract(client) -> None:
    """AgentRun step output_data 支持 {total, items} 结构。

    P0: 真实 chat retrieve step 写入 {total, items}，前端 extractChunks
    需兼容此结构。本测试锁定该契约：任何 step 的 output_data 若含 items
    字段，则 items 必须是 list。
    """
    headers = auth_headers(client, username="alice")
    run_id = _create_chat_run(client, headers, "retrieve契约课程", "什么是进程？")

    resp = client.get(f"/api/v1/agent-runs/{run_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["steps"], list)
    # 契约：任何 step 的 output_data 若含 items 字段，items 必须是 list
    for step in body["steps"]:
        out = step.get("output_data")
        if out and isinstance(out, dict) and "items" in out:
            assert isinstance(out["items"], list), (
                f"step {step.get('step_name')} output_data.items must be list"
            )


# ---------------------------------------------------------------------------
# Concept graph contract (P6)
# ---------------------------------------------------------------------------


def test_concept_graph_response_contract(client) -> None:
    """GET /concept-graph 返回 {nodes: [...], edges: [...]} 结构。

    锁定前端 conceptGraph.ts GraphResponse 接口契约：
    - 顶层字段为 nodes + edges
    - 两者均为 list
    - node 至少含 id/title/course_id 字段
    - edge 至少含 id/source_node_id/target_node_id/relation_type/status 字段
    """
    headers = auth_headers(client, username="alice")
    create_course(client, headers, name="操作系统")
    # rebuild is safe to call with 0 KPs (returns 0/0)
    client.post("/api/v1/concept-graph/rebuild", headers=headers)
    resp = client.get("/api/v1/concept-graph", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {"nodes", "edges"}
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)
    for node in body["nodes"]:
        assert isinstance(node, dict)
        assert "id" in node
        assert "title" in node
        assert "course_id" in node
    for edge in body["edges"]:
        assert isinstance(edge, dict)
        assert "id" in edge
        assert "source_node_id" in edge
        assert "target_node_id" in edge
        assert "relation_type" in edge
        assert "status" in edge


def test_concept_graph_rebuild_response_contract(client) -> None:
    """POST /concept-graph/rebuild 返回 {nodes_count, edges_count} 结构。"""
    headers = auth_headers(client, username="alice")
    create_course(client, headers, name="操作系统")
    resp = client.post("/api/v1/concept-graph/rebuild", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {"nodes_count", "edges_count"}
    assert isinstance(body["nodes_count"], int)
    assert isinstance(body["edges_count"], int)


def test_concept_graph_compare_error_contract(client) -> None:
    """compare 404 返回统一 {code, message} 格式。"""
    headers = auth_headers(client, username="alice")
    resp = client.post(
        "/api/v1/concept-graph/compare", headers=headers,
        json={"source_node_id": 99999, "target_node_id": 99998},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert set(body.keys()) >= {"code", "message"}
    assert "detail" not in body
