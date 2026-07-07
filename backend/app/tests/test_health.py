"""Tests for the health check endpoint."""
import pytest


def test_health_returns_ok(client) -> None:
    """GET /api/v1/health should return 200 with body {"status": "ok"}."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
