#!/usr/bin/env python
"""Run the isolated, secret-safe real-provider RC acceptance suite."""
from __future__ import annotations

import argparse
import hashlib
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.real_llm_acceptance_service import (  # noqa: E402
    assert_real_llm_meta,
    base_url_host,
    redact_secrets,
    scan_artifact_tree,
    safe_failure_record,
)

FIXTURE_TEXT = """计算机网络：数据链路层基础

第一节 成帧与差错检测
帧是数据链路层的协议数据单元。成帧的作用是把网络层交付的数据组织为可在链路上传输的单位。接收方需要识别帧的开始和结束，才能把连续比特流恢复为独立帧。CRC 是循环冗余校验，用于差错检测。发送方根据帧内容计算 CRC 校验值，接收方重新计算后比较校验值。CRC 可以发现传输中的许多比特错误，但本资料不把它描述为纠错机制。

第二节 停止等待协议
停止等待协议每发送一帧后等待确认。只有收到当前帧的确认后，发送方才发送下一帧。若确认没有在规定时间内到达，发送方会重传当前帧。序号可以帮助接收方识别重复帧。停止等待协议结构简单，但在传播时延较大时链路利用率较低。

第三节 滑动窗口协议
滑动窗口允许多个未确认帧同时在途。发送窗口限定发送方在未收到确认前最多可以连续发送的帧数。接收窗口用于描述接收方当前可接受的序号范围。确认到达后，发送窗口向前滑动并允许发送新的帧。相较停止等待，滑动窗口能提高链路利用率，但需要处理窗口边界与序号管理。
"""
INSUFFICIENT_EVIDENCE_PHRASES = ("资料中未提供", "根据当前资料无法", "资料不足", "未检索到相关内容")


class AcceptanceFailure(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pick_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_path(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.write_bytes(payload.encode("utf-8"))


def _write_evidence_manifest(root: Path, summary: dict, audited_runs: list[dict]) -> None:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "evidence-manifest.json":
            relative = path.relative_to(root).as_posix()
            data = path.read_bytes()
            files[relative] = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    manifest = {"schema_version": 1, "run_id": summary["run_id"], "tested_code_sha": summary["tested_code_sha"], "generated_at": _utc_now(), "provider": summary["provider"], "base_url_host": summary["base_url_host"], "model": summary["model"], "scenario_count": summary["scenario_count"], "passed": summary["passed"], "audited_agent_run_count": len(audited_runs), "fallback_count": summary["fallback_count"], "mock_count": summary["mock_count"], "degraded_count": summary["degraded_count"], "meta_missing_count": summary["meta_missing_count"], "secret_scan_status": summary["secret_scan"]["status"], "files": files}
    _json_path(root / "evidence-manifest.json", manifest)


def _clean_text(text: str) -> str:
    return redact_secrets(text)


def _copy_redacted_log(source: Path, destination: Path) -> None:
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(_clean_text(source.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")


def _request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> dict:
    response = client.request(method, path, **kwargs)
    if response.status_code >= 400:
        raise AcceptanceFailure(f"HTTP_{response.status_code} {path}: {_clean_text(response.text)}")
    try:
        return response.json()
    except ValueError as exc:
        raise AcceptanceFailure(f"NON_JSON_API_RESPONSE {path}: {_clean_text(response.text)}") from exc


def _wait_for_api(client: httpx.Client, timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if client.get("/api/v1/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise AcceptanceFailure("API_START_TIMEOUT")


def _wait_for_parse(client: httpx.Client, material_public_id: str, timeout: int = 90) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        last = _request(client, "GET", f"/api/v1/materials/{material_public_id}/readiness")
        if str(last.get("status") or "") == "ready":
            return last
        if str(last.get("status") or "") == "failed":
            raise AcceptanceFailure(f"PARSE_FAILED: {_clean_text(json.dumps(last, ensure_ascii=False))}")
        time.sleep(0.5)
    raise AcceptanceFailure(f"PARSE_TIMEOUT: {_clean_text(json.dumps(last, ensure_ascii=False))}")


def _runs(client: httpx.Client) -> list[dict]:
    return _request(client, "GET", "/api/v1/agent-runs", params={"limit": 200}).get("items", [])


def _assert_new_real_run(client: httpx.Client, before_ids: set[int], expected_type: str) -> dict:
    candidates = [run for run in _runs(client) if run.get("id") not in before_ids and run.get("run_type") == expected_type]
    if not candidates:
        raise AcceptanceFailure(f"AGENT_AUDIT_MISSING:{expected_type}")
    run = candidates[0]
    output = run.get("output_summary") or {}
    status = run.get("status")
    if status != "success":
        raise AcceptanceFailure(f"AGENT_RUN_NOT_SUCCESS:{expected_type}:{status or 'missing'}")
    meta_observed = output.get("meta_observed")
    fallback_used = run.get("fallback_used")
    # Never infer observation from provider/model fields and never coerce None
    # into False. The checker receives the exact persisted audit values.
    assert_real_llm_meta({
        "provider": run.get("provider"),
        "actual_provider": run.get("actual_provider"),
        "model_name": run.get("model_name"),
        "actual_model": run.get("actual_model"),
        "fallback_used": fallback_used,
        "degraded": status == "degraded",
        "meta_observed": meta_observed,
    })
    return {key: run.get(key) for key in ("run_type", "status", "actual_provider", "actual_model", "fallback_used", "duration_ms")} | {
        "meta_observed": meta_observed,
        "repair_attempted": bool(output.get("repair_attempted")),
        "repair_success": bool(output.get("repair_success")),
        "llm_call_count": int(output.get("llm_call_count") or 1),
        "initial_contract": output.get("initial_contract"),
        "repair_contract": output.get("repair_contract"),
    }


def _scenario(name: str, fn, results: list[dict]) -> None:
    started = time.monotonic()
    try:
        results.append({"id": name, "status": "passed", "latency_ms": int((time.monotonic() - started) * 1000), "detail": fn()})
    except Exception as exc:
        results.append({"id": name, "status": "failed", "latency_ms": int((time.monotonic() - started) * 1000), **safe_failure_record(exc)})
        raise


def _start_process(args: list[str], env: dict[str, str], log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(args, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _scenario_suite(client: httpx.Client, key: str, provider: str, base_url: str, model: str, scenarios: list[dict], audit_runs: list[dict]) -> None:
    username = f"test-real-llm-{secrets.token_hex(4)}"
    password = "test1234"
    _scenario("REAL-01-model-config", lambda: _configure(client, username, password, key, provider, base_url, model), scenarios)
    course = _request(client, "POST", "/api/v1/courses", json={"name": "真实模型验收：数据链路层", "teacher": "acceptance", "semester": "RC3"})
    course_id = course["id"]
    upload = _request(client, "POST", f"/api/v1/courses/{course_id}/materials", files={"file": ("data-link-layer.txt", FIXTURE_TEXT.encode("utf-8"), "text/plain")})
    material_public_id = upload["public_id"]
    _request(client, "POST", f"/api/v1/materials/{material_public_id}/parse")
    _wait_for_parse(client, material_public_id)

    def knowledge_points() -> dict:
        before = {run["id"] for run in _runs(client)}
        data = _request(client, "POST", f"/api/v1/courses/{course_id}/knowledge-points/generate")
        points = data.get("knowledge_points") or []
        run = _assert_new_real_run(client, before, "outline")
        audit_runs.append(run)
        missing_sources = sum(not point.get("source_chunk_ids") for point in points)
        if len(points) < 2 or missing_sources:
            raise AcceptanceFailure(f"KNOWLEDGE_POINT_EVIDENCE_CONTRACT_FAILED: count={len(points)} missing_sources={missing_sources}")
        initial, repaired = run.get("initial_contract") or {}, run.get("repair_contract") or {}
        return {"knowledge_point_count": len(points), "initial_valid_count": initial.get("valid_count", len(points)), "repair_attempted": run["repair_attempted"], "final_valid_count": repaired.get("valid_count", len(points)), "source_bound_count": len(points) - missing_sources}

    _scenario("REAL-02-knowledge-points", knowledge_points, scenarios)
    conversation = _request(client, "POST", "/api/v1/conversations", json={"course_id": course_id, "title": "真实模型验收"})

    def chat() -> dict:
        before = {run["id"] for run in _runs(client)}
        data = _request(client, "POST", "/api/v1/chat", json={"course_id": course_id, "conversation_id": conversation["id"], "question": "CRC 在这份资料中的作用是什么？"})
        if "差错检测" not in str(data.get("answer") or "") or not data.get("citations"):
            raise AcceptanceFailure("CHAT_GROUNDING_CONTRACT_FAILED")
        if any(citation.get("material_public_id") != material_public_id for citation in data["citations"]):
            raise AcceptanceFailure("CHAT_CITATION_MATERIAL_MISMATCH")
        audit_runs.append(_assert_new_real_run(client, before, "course_qa"))
        out_of_scope = _request(client, "POST", "/api/v1/chat", json={"course_id": course_id, "conversation_id": conversation["id"], "question": "这份资料如何解释 BGP 路由聚合？"})
        answer = str(out_of_scope.get("answer") or "").strip()
        if out_of_scope.get("citations"):
            raise AcceptanceFailure("OUT_OF_SCOPE_FABRICATED_CITATION")
        if out_of_scope.get("not_found") is not True:
            raise AcceptanceFailure("OUT_OF_SCOPE_NOT_FOUND_FLAG_MISSING")
        if not any(phrase in answer for phrase in INSUFFICIENT_EVIDENCE_PHRASES):
            raise AcceptanceFailure("OUT_OF_SCOPE_INSUFFICIENT_EVIDENCE_MISSING")
        if len(answer) > 160 or answer.count("。") > 3:
            raise AcceptanceFailure("OUT_OF_SCOPE_UNGROUNDED_BODY_PRESENT")
        return {"citation_count": len(data["citations"]), "out_of_scope_not_found": True, "out_of_scope_answer_length": len(answer)}

    _scenario("REAL-03-chat-and-citations", chat, scenarios)

    def quiz() -> dict:
        before = {run["id"] for run in _runs(client)}
        data = _request(client, "POST", "/api/v1/quizzes", json={"course_id": course_id, "question_count": 1, "question_types": ["choice"]})
        items = data.get("items") or []
        if len(items) != 1 or any(not item.get("source_evidence") for item in items):
            raise AcceptanceFailure("QUIZ_EVIDENCE_CONTRACT_FAILED")
        audit_runs.append(_assert_new_real_run(client, before, "quiz"))
        result = _request(client, "POST", f"/api/v1/quizzes/{data['id']}/submit", json={"answers": [{"item_id": item["id"], "user_answer": "Z"} for item in items]})
        weak = _request(client, "GET", f"/api/v1/courses/{course_id}/weak-points")
        if not weak.get("items"):
            raise AcceptanceFailure("WEAK_POINT_NOT_CREATED")
        return {"quiz_id": data["id"], "score": result.get("score"), "weak_points": len(weak["items"])}

    _scenario("REAL-04-quiz-and-weak-point", quiz, scenarios)

    def plan() -> dict:
        before = {run["id"] for run in _runs(client)}
        requested_deadline = (date.today() + timedelta(days=2)).isoformat()
        data = _request(client, "POST", "/api/v1/plans", json={"goal": "两天内复习数据链路层", "course_ids": [course_id], "deadline": requested_deadline, "daily_minutes": 90})
        tasks = data.get("tasks") or []
        if not tasks:
            raise AcceptanceFailure("PLAN_TASKS_MISSING")
        if any(task.get("course_id") != course_id for task in tasks):
            raise AcceptanceFailure("PLAN_COURSE_TARGET_MISMATCH")
        if any((task.get("target_spec") or {}).get("material_public_id") not in {None, material_public_id} for task in tasks):
            raise AcceptanceFailure("PLAN_FOREIGN_MATERIAL_TARGET")
        material_study_tasks = [task for task in tasks if task.get("task_type") == "learn" and task.get("target_type") == "material" and (task.get("target_spec") or {}).get("material_public_id") == material_public_id]
        if not material_study_tasks:
            raise AcceptanceFailure("PLAN_MATERIAL_STUDY_TARGET_MISSING")
        if str((data.get("goal") or {}).get("deadline") or "") != requested_deadline:
            raise AcceptanceFailure("PLAN_DEADLINE_MISMATCH")
        audit_runs.append(_assert_new_real_run(client, before, "planner"))
        return {"task_count": len(tasks), "bound_material_task_count": len(material_study_tasks), "deadline": requested_deadline}

    _scenario("REAL-05-learning-plan", plan, scenarios)

    def overview() -> dict:
        before = {run["id"] for run in _runs(client)}
        data = _request(client, "POST", f"/api/v1/materials/{material_public_id}/study-guide")
        answer = str(data.get("answer") or "")
        if not any(term in answer for term in ("CRC", "停止等待", "滑动窗口")) or not data.get("evidence_ids"):
            raise AcceptanceFailure("OVERVIEW_EVIDENCE_CONTRACT_FAILED")
        audit_runs.append(_assert_new_real_run(client, before, "material_overview"))
        return {"evidence_count": len(data["evidence_ids"])}

    _scenario("REAL-06-material-overview", overview, scenarios)


def _configure(client: httpx.Client, username: str, password: str, key: str, provider: str, base_url: str, model: str) -> dict:
    _request(client, "POST", "/api/v1/auth/register", json={"username": username, "password": password})
    token = _request(client, "POST", "/api/v1/auth/login", json={"username": username, "password": password})["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    config = _request(client, "POST", "/api/v1/llm-configs", json={"provider": provider, "name": "isolated-real-acceptance", "base_url": base_url, "model": model, "api_key": key, "temperature": 0, "max_tokens": 2000, "timeout_seconds": 60})
    if _request(client, "POST", f"/api/v1/llm-configs/{config['id']}/test").get("status") != "success":
        raise AcceptanceFailure("REAL_LLM_CONNECTION_FAILED")
    _request(client, "POST", f"/api/v1/llm-configs/{config['id']}/enable")
    active = _request(client, "GET", "/api/v1/llm-configs/active")
    if not active.get("config") or active["config"].get("api_key_masked") in {key, ""}:
        raise AcceptanceFailure("LLM_CONFIG_SECRET_EXPOSURE_OR_ENABLE_FAILED")
    return {"provider": provider, "model": model, "config_id": config["id"]}


def run(args: argparse.Namespace) -> int:
    key = os.environ.get("REAL_LLM_API_KEY", "")
    if not key:
        raise AcceptanceFailure("REAL_LLM_API_KEY is required in the environment")
    if not args.base_url or not args.model:
        raise AcceptanceFailure("--base-url and --model are required")
    run_id = args.run_id or f"real-llm-{int(time.time())}-{secrets.token_hex(3)}"
    artifact_dir = (ROOT / args.artifact_root / run_id).resolve()
    runtime_dir = (ROOT / ".real-llm-runs" / run_id).resolve()
    staging_dir = runtime_dir / "artifact-staging"
    if artifact_dir.exists() or runtime_dir.exists():
        raise AcceptanceFailure(f"RUN_ID_ALREADY_EXISTS:{run_id}")
    runtime_dir.mkdir(parents=True)
    logs_dir = runtime_dir / "logs"
    started_at, port = _utc_now(), _pick_port()
    env = os.environ.copy()
    env.update({"PYTHONPATH": str(ROOT / "backend"), "DATABASE_URL": f"sqlite:///{(runtime_dir / 'acceptance.db').as_posix()}", "UPLOAD_DIR": str(runtime_dir / "uploads"), "PARSED_DIR": str(runtime_dir / "parsed"), "LLM_PROVIDER": "mock", "REAL_LLM_ACCEPTANCE_MODE": "true", "REAL_LLM_ACCEPTANCE_RUN_ID": run_id, "REAL_LLM_ACCEPTANCE_OUTPUT_DIR": str(artifact_dir), "APP_GIT_COMMIT": _git_sha()})
    backend = worker = None
    scenarios: list[dict] = []
    audit_runs: list[dict] = []
    failure: dict | None = None
    try:
        subprocess.run([sys.executable, "scripts/init_db.py"], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        backend = _start_process([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], env, logs_dir / "backend.raw.log")
        worker = _start_process([sys.executable, "scripts/run_parse_worker.py"], env, logs_dir / "worker.raw.log")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=180.0) as client:
            _wait_for_api(client)
            _scenario_suite(client, key, args.provider, args.base_url, args.model, scenarios, audit_runs)
    except Exception as exc:
        failure = safe_failure_record(exc)
    finally:
        _stop_process(worker)
        _stop_process(backend)
        _copy_redacted_log(logs_dir / "backend.raw.log", staging_dir / "logs" / "backend.redacted.log")
        _copy_redacted_log(logs_dir / "worker.raw.log", staging_dir / "logs" / "worker.redacted.log")

    summary = {
        "schema_version": 1, "tested_code_sha": _git_sha(), "run_id": run_id,
        "provider": args.provider, "base_url_host": base_url_host(args.base_url), "model": args.model,
        "all_passed": failure is None and len(scenarios) == 6 and all(item["status"] == "passed" for item in scenarios),
        "fallback_count": sum(run.get("fallback_used") is True for run in audit_runs),
        "mock_count": sum(run.get("actual_provider") == "mock" for run in audit_runs),
        "degraded_count": sum(run.get("status") == "degraded" for run in audit_runs),
        "meta_missing_count": sum(run.get("meta_observed") is not True for run in audit_runs),
        "repair_attempt_count": sum(bool(run.get("repair_attempted")) for run in audit_runs),
        "repair_success_count": sum(bool(run.get("repair_success")) for run in audit_runs),
        "llm_call_count": sum(int(run.get("llm_call_count") or 1) for run in audit_runs),
        "all_meta_observed": all(run.get("meta_observed") is True for run in audit_runs),
        "scenario_count": len(scenarios), "passed": sum(item["status"] == "passed" for item in scenarios),
        "failed": sum(item["status"] == "failed" for item in scenarios),
        "secret_scan": {"status": "pending", "files_scanned": 0, "patterns_checked": 0, "matches": 0},
        "started_at": started_at, "finished_at": _utc_now(),
    }
    if summary["fallback_count"] or summary["mock_count"] or summary["degraded_count"] or summary["meta_missing_count"]:
        summary["all_passed"] = False
        failure = failure or {"error_code": "REAL_LLM_STRICT_META_FAILED", "error": "real acceptance observed fallback, mock, degraded, or missing metadata"}
    _json_path(staging_dir / "real-llm-acceptance.json", summary)
    _json_path(staging_dir / "scenario-results.json", scenarios)
    _json_path(staging_dir / "redacted-agent-runs.json", audit_runs)
    _json_path(staging_dir / "environment-fingerprint.json", {"python": sys.version.split()[0], "platform": sys.platform, "base_url_host": base_url_host(args.base_url)})
    _json_path(staging_dir / "request-summary.json", {"scenario_ids": [item["id"] for item in scenarios], "failure": failure})
    scan = scan_artifact_tree(staging_dir, key)
    summary["secret_scan"] = scan
    if scan["status"] == "passed":
        _json_path(staging_dir / "real-llm-acceptance.json", summary)
        _write_evidence_manifest(staging_dir, summary, audit_runs)
        scan = scan_artifact_tree(staging_dir, key)
        if scan["status"] != "passed":
            summary["all_passed"] = False
            failure = {"error_code": "REAL_LLM_SECRET_SCAN_FAILED", "error": "manifest scan reported matches"}
            shutil.rmtree(staging_dir, ignore_errors=True)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            _json_path(artifact_dir / "real-llm-acceptance.json", summary)
            _json_path(artifact_dir / "request-summary.json", {"scenario_ids": [item["id"] for item in scenarios], "failure": failure})
            shutil.rmtree(runtime_dir, ignore_errors=True)
            return 1
        artifact_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_dir, artifact_dir)
    else:
        summary["all_passed"] = False
        failure = failure or {"error_code": "REAL_LLM_SECRET_SCAN_FAILED", "error": "artifact secret scan reported matches"}
        shutil.rmtree(staging_dir, ignore_errors=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        _json_path(artifact_dir / "real-llm-acceptance.json", summary)
        _json_path(artifact_dir / "request-summary.json", {"scenario_ids": [item["id"] for item in scenarios], "failure": failure})
    shutil.rmtree(runtime_dir, ignore_errors=True)
    return 0 if summary["all_passed"] else 1


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default=os.getenv("REAL_LLM_PROVIDER", "openai-compatible"))
    parser.add_argument("--base-url", default=os.getenv("REAL_LLM_BASE_URL", ""))
    parser.add_argument("--model", default=os.getenv("REAL_LLM_MODEL", ""))
    parser.add_argument("--artifact-root", default="artifacts/verification/real-llm")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as exc:
        print(_clean_text(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
