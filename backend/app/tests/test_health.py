"""Tests for the health check endpoint."""
import pytest


def test_health_returns_ok(client) -> None:
    """GET /api/v1/health should return 200 with status=ok and app identity."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "course-learning-agent"
    assert "version" in body
    assert isinstance(body["version"], str)
    assert body["version"]  # non-empty


def test_health_response_contains_project_identifier_for_launcher(client) -> None:
    """The launcher reuses port 8000 only if /health identifies this project.

    Task C: the response body must contain the literal ``course-learning-agent``
    string so ``start_windows.ps1`` can distinguish this backend from other
    FastAPI projects that happen to bind the same port.
    """
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert "course-learning-agent" in response.text


def test_health_returns_build_info(client) -> None:
    """Task D: /health must expose a ``build`` object with git_commit,
    launch_id and started_at so the Windows launcher can detect when port
    8000 is held by a stale backend running an older commit.
    """
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert "build" in body
    build = body["build"]
    assert isinstance(build, dict)
    # git_commit may be empty in dev, but the field must be present and a str.
    assert "git_commit" in build
    assert isinstance(build["git_commit"], str)
    assert "launch_id" in build
    assert isinstance(build["launch_id"], str)
    assert "started_at" in build
    assert isinstance(build["started_at"], str)
    assert build["started_at"]  # non-empty ISO timestamp


# T09: 生产环境硬化 — 默认密钥在生产环境应被拒绝


def test_prod_rejects_default_jwt_secret(monkeypatch) -> None:
    """T09: ENVIRONMENT=production + 默认 JWT_SECRET_KEY 应启动失败。"""
    from app.core.config import Settings

    s = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="change_me",
        LLM_CONFIG_SECRET_KEY="a-valid-fernet-key",
    )
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        s.validate_prod_secrets()


def test_prod_rejects_default_llm_config_secret(monkeypatch) -> None:
    """T09: ENVIRONMENT=production + 默认 LLM_CONFIG_SECRET_KEY 应启动失败。"""
    from app.core.config import Settings

    s = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a-real-secret",
        LLM_CONFIG_SECRET_KEY="change-me-please",
    )
    with pytest.raises(ValueError, match="LLM_CONFIG_SECRET_KEY"):
        s.validate_prod_secrets()


def test_dev_allows_default_secrets() -> None:
    """T09: 开发环境允许使用默认密钥（不抛异常）。"""
    from app.core.config import Settings

    s = Settings(
        ENVIRONMENT="development",
        JWT_SECRET_KEY="change_me",
        LLM_CONFIG_SECRET_KEY="change-me-please",
    )
    # 不应抛异常
    s.validate_prod_secrets()


def test_cors_origin_list_parses_comma_separated() -> None:
    """T09: cors_origin_list 正确解析逗号分隔的来源列表。"""
    from app.core.config import Settings

    s = Settings(CORS_ORIGINS="http://a.com, http://b.com ,http://c.com")
    origins = s.cors_origin_list()
    assert origins == ["http://a.com", "http://b.com", "http://c.com"]


# T04: 生产环境硬化 — 拒绝 CORS_ORIGINS="*" 误配


def test_prod_rejects_wildcard_cors() -> None:
    """T04: ENVIRONMENT=production 且 CORS_ORIGINS='*' 应启动校验失败。"""
    from app.core.config import Settings

    s = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a-real-secret",
        LLM_CONFIG_SECRET_KEY="a-valid-fernet-key",
        CORS_ORIGINS="*",
    )
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        s.validate_prod_secrets()


def test_prod_rejects_empty_cors() -> None:
    """T04: ENVIRONMENT=production 且 CORS_ORIGINS 为空也应启动校验失败。"""
    from app.core.config import Settings

    s = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="a-real-secret",
        LLM_CONFIG_SECRET_KEY="a-valid-fernet-key",
        CORS_ORIGINS="",
    )
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        s.validate_prod_secrets()


def test_prod_rejects_default_jwt_secret_case_insensitive() -> None:
    """T0-3: ENVIRONMENT="Production"（首字母大写）也应触发生产校验。"""
    from app.core.config import Settings

    s = Settings(
        ENVIRONMENT="Production",
        JWT_SECRET_KEY="change_me",
        LLM_CONFIG_SECRET_KEY="a-valid-fernet-key",
    )
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        s.validate_prod_secrets()


def test_prod_rejects_default_jwt_secret_uppercase() -> None:
    """T0-3: ENVIRONMENT="PRODUCTION"（全大写）也应触发生产校验。"""
    from app.core.config import Settings

    s = Settings(
        ENVIRONMENT="PRODUCTION",
        JWT_SECRET_KEY="change_me",
        LLM_CONFIG_SECRET_KEY="a-valid-fernet-key",
    )
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        s.validate_prod_secrets()
