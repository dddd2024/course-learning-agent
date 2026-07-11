"""V3 Agent Status tests (BASE-V3-02).

These tests capture audit blockers in agent-run status management where:

- When the user's LLM config fails and the system model succeeds, the
  AgentRun status should be ``degraded`` (not ``success``).
- When no evidence is found during retrieval, the AgentRun status
  should be ``insufficient_evidence`` (not ``success``).
- ``finish_run(success)`` should NOT override a previously set
  ``degraded`` status.
- The AgentRun response should expose ``fallback_chain``,
  ``evidence_status``, and ``final_status`` so the frontend can surface
  degradation to the user.

Written to FAIL on the current codebase.
"""
from app.agents.audit import AgentAudit
from app.models.audit import AgentRun
from app.tests.conftest import (
    auth_headers,
    create_course,
    setup_course_with_material,
)

TLB_TEXT = (
    "操作系统课程笔记\n"
    "快表 TLB 是页表的高速缓存，用于加速虚拟地址到物理地址的转换。\n"
    "页表存储虚拟页到物理页的映射关系。\n"
    "TLB 命中时无需访问内存中的页表，提升了地址转换速度。\n"
).encode("utf-8")


def test_degraded_status_when_user_model_fails(
    client, db_session, tmp_path, monkeypatch
) -> None:
    """When user model fails and system model succeeds, status='degraded'.

    The current code marks the run as ``success`` even when a fallback
    occurred.  The V3 fix should mark it ``degraded`` so the audit trail
    and the user-facing UI can surface the degradation.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "降级测试"},
        headers=headers,
    )
    assert conv_resp.status_code == 201, conv_resp.text
    conversation_id = conv_resp.json()["id"]

    def fake_answer(db, course_id, question, ranked, course_name, user_config=None, **kwargs):
        top = ranked[0] if ranked else {"chunk_id": 1}
        quote = (top.get("text") or "")[:50]
        return {
            "answer": "快表是页表的高速缓存。",
            "key_points": ["加速地址转换"],
            "citations": [
                {
                    "chunk_id": top["chunk_id"],
                    "quote_text": quote,
                    "claim_text": "快表是页表的高速缓存",
                    "support_status": "verified",
                    "verification_reason": "原文精确匹配",
                    "confidence": 0.85,
                },
            ],
            "not_found": False,
            "follow_up_questions": [],
            "retrieved_chunks": [],
            "reliability_level": "medium",
            # Simulate: user model failed, system model succeeded.
            "provider": "real",
            "fallback_used": True,
            "fallback_reason": "user config timeout",
        }

    monkeypatch.setattr("app.services.chat_service.answer_question", fake_answer)

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    agent_run_id = body.get("agent_run_id")
    assert agent_run_id is not None, "Response missing agent_run_id"

    # Fetch the agent run detail.
    run_resp = client.get(
        f"/api/v1/agent-runs/{agent_run_id}",
        headers=headers,
    )
    assert run_resp.status_code == 200, run_resp.text
    run_body = run_resp.json()

    # The status should be "degraded", not "success".
    assert run_body["status"] == "degraded", (
        f"Expected status='degraded' when user model failed and system "
        f"succeeded, got status='{run_body['status']}'"
    )


def test_insufficient_evidence_status_when_no_chunks(
    client, tmp_path, monkeypatch
) -> None:
    """When no evidence is found, status='insufficient_evidence'.

    The current code marks the run as ``success`` even when no chunks
    were retrieved.  The V3 fix should use ``insufficient_evidence``.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    # Create a course with NO material — so retrieval returns nothing.
    course_id = create_course(client, headers, name="空课程")

    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "无证据测试"},
        headers=headers,
    )
    assert conv_resp.status_code == 201, conv_resp.text
    conversation_id = conv_resp.json()["id"]

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    agent_run_id = body.get("agent_run_id")
    assert agent_run_id is not None, "Response missing agent_run_id"

    run_resp = client.get(
        f"/api/v1/agent-runs/{agent_run_id}",
        headers=headers,
    )
    assert run_resp.status_code == 200, run_resp.text
    run_body = run_resp.json()

    assert run_body["status"] == "insufficient_evidence", (
        f"Expected status='insufficient_evidence' when no evidence found, "
        f"got status='{run_body['status']}'"
    )


def test_finish_run_success_does_not_override_degraded(db_session, sample_user) -> None:
    """finish_run(success) must NOT override a previously set 'degraded' status.

    The current ``finish_run`` unconditionally sets ``run.status = status``.
    The V3 fix should preserve a ``degraded`` status when ``finish_run`` is
    called with ``status='success'``.
    """
    run = AgentAudit.create_run(
        db_session,
        user_id=sample_user.id,
        run_type="course_qa",
        model_name="mock",
        provider="mock",
    )
    db_session.commit()

    # Simulate update_run_meta setting degraded.
    run.status = "degraded"
    db_session.commit()

    # Now finish_run is called with success (as chat_service does).
    AgentAudit.finish_run(
        db_session,
        run_id=run.id,
        status="success",
        output_summary={"answer": "test"},
    )
    db_session.commit()

    db_session.refresh(run)
    assert run.status == "degraded", (
        f"finish_run(success) overrode 'degraded' to '{run.status}' — "
        f"a previously set degraded status must be preserved"
    )


def test_agent_run_response_includes_v3_fields(
    client, tmp_path, monkeypatch
) -> None:
    """AgentRun response should include fallback_chain, evidence_status, final_status.

    The current AgentRunResponse schema does not expose these fields.
    The V3 fix should add them so the frontend can surface the full
    degradation picture.
    """
    monkeypatch.setattr("app.core.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.core.config.settings.PARSED_DIR", str(tmp_path / "parsed"))

    headers = auth_headers(client, username="alice")
    course_id, _ = setup_course_with_material(client, headers, content=TLB_TEXT)

    conv_resp = client.post(
        "/api/v1/conversations",
        json={"course_id": course_id, "title": "字段测试"},
        headers=headers,
    )
    assert conv_resp.status_code == 201, conv_resp.text
    conversation_id = conv_resp.json()["id"]

    def fake_answer(db, course_id, question, ranked, course_name, user_config=None, **kwargs):
        top = ranked[0] if ranked else {"chunk_id": 1}
        quote = (top.get("text") or "")[:50]
        return {
            "answer": "快表是页表的高速缓存。",
            "key_points": ["加速地址转换"],
            "citations": [
                {
                    "chunk_id": top["chunk_id"],
                    "quote_text": quote,
                    "claim_text": "快表是页表的高速缓存",
                    "support_status": "verified",
                    "verification_reason": "原文精确匹配",
                    "confidence": 0.85,
                },
            ],
            "not_found": False,
            "follow_up_questions": [],
            "retrieved_chunks": [],
            "reliability_level": "high",
            "provider": "mock",
            "fallback_used": False,
            "fallback_reason": None,
        }

    monkeypatch.setattr("app.services.chat_service.answer_question", fake_answer)

    resp = client.post(
        "/api/v1/chat",
        json={
            "course_id": course_id,
            "conversation_id": conversation_id,
            "question": "什么是快表？",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    agent_run_id = resp.json().get("agent_run_id")
    assert agent_run_id is not None

    run_resp = client.get(
        f"/api/v1/agent-runs/{agent_run_id}",
        headers=headers,
    )
    assert run_resp.status_code == 200, run_resp.text
    run_body = run_resp.json()

    # fallback_chain: list of {provider, status, reason?} entries.
    assert "fallback_chain" in run_body, (
        "AgentRun response missing 'fallback_chain' field"
    )
    # evidence_status: string describing evidence quality.
    assert "evidence_status" in run_body, (
        "AgentRun response missing 'evidence_status' field"
    )
    # final_status: the definitive status (degraded / success / failed / ...).
    assert "final_status" in run_body, (
        "AgentRun response missing 'final_status' field"
    )
