"""Application configuration loaded from environment variables."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic_settings import BaseSettings, SettingsConfigDict

# Default secret values that must NOT be used in production.
_DEFAULT_JWT_SECRET = "change_me"
_DEFAULT_LLM_CONFIG_SECRET = "change-me-please"


class Settings(BaseSettings):
    """Runtime settings for the course learning assistant backend.

    Values are read from environment variables, falling back to the
    defaults below. A ``.env`` file next to the application is also
    honoured.
    """

    DATABASE_URL: str = "sqlite:///./course_assistant.db"
    JWT_SECRET_KEY: str = _DEFAULT_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    UPLOAD_DIR: str = "../storage/uploads"
    PARSED_DIR: str = "../storage/parsed"
    LLM_PROVIDER: str = "mock"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = ""
    LLM_TIMEOUT_SECONDS: int = 60
    # Task 9: concept compare can take longer than the default 60s
    # timeout on first call, so give it a dedicated, longer window.
    LLM_CONCEPT_COMPARE_TIMEOUT_SECONDS: int = 120
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 2000
    LLM_CONFIG_SECRET_KEY: str = _DEFAULT_LLM_CONFIG_SECRET
    EMBEDDING_PROVIDER: str = "mock"
    MAX_UPLOAD_MB: int = 30
    # Phase 2 Task B: trace persistence level.
    # - "error": only persist steps when the run fails (default)
    # - "always": persist all steps (verbose, for debugging)
    # - "off": never persist steps (audit run header only)
    AGENT_TRACE_MODE: str = "error"
    # T09: environment + CORS hardening.
    ENVIRONMENT: str = "development"  # development | production
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Task C: project identity exposed by /api/v1/health so the Windows
    # launcher can verify port 8000 actually serves this backend.
    APP_NAME: str = "course-learning-agent"
    APP_VERSION: str = "0.1.0"
    # Task D: build identity for /health. APP_GIT_COMMIT is injected by
    # start_windows.ps1 (via $env:APP_GIT_COMMIT = git rev-parse HEAD) so
    # the launcher can detect when port 8000 is held by a stale backend
    # running an older commit. APP_LAUNCH_ID is generated per-process.
    APP_GIT_COMMIT: str = ""
    APP_LAUNCH_ID: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def upload_path(self) -> Path:
        return Path(self.UPLOAD_DIR)

    @property
    def parsed_path(self) -> Path:
        return Path(self.PARSED_DIR)

    def cors_origin_list(self) -> list[str]:
        """Parse ``CORS_ORIGINS`` into a list of allowed origin strings."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def validate_prod_secrets(self) -> None:
        """Reject default secret values when ``ENVIRONMENT=production``.

        Raises ``ValueError`` if any secret still holds its default
        placeholder value, or if ``CORS_ORIGINS`` is empty or contains
        the ``*`` wildcard (a misconfiguration that would disable the
        same-origin policy in production). In development this is a
        no-op so the platform runs out-of-the-box without configuration.
        """
        # T0-3: ENVIRONMENT 判断大小写不敏感，Production/PRODUCTION 均触发。
        if self.ENVIRONMENT.lower() != "production":
            return
        if self.JWT_SECRET_KEY in (_DEFAULT_JWT_SECRET, ""):
            raise ValueError(
                "生产环境不能使用默认 JWT_SECRET_KEY，请设置一个随机长字符串。"
            )
        if self.LLM_CONFIG_SECRET_KEY in (_DEFAULT_LLM_CONFIG_SECRET, ""):
            raise ValueError(
                "生产环境不能使用默认 LLM_CONFIG_SECRET_KEY，请设置一个 "
                "Fernet 兼容密钥。"
            )
        # T04: production 下拒绝 CORS_ORIGINS="*" 或空来源，避免误配置
        # 关闭同源策略。
        origins = self.cors_origin_list()
        if not origins or "*" in origins:
            raise ValueError(
                "生产环境不能使用 CORS_ORIGINS='*' 或空来源，请设置实际前端域名。"
            )


settings = Settings()

# Task D: process-wide launch metadata exposed via /health. ``started_at``
# is captured once at import time so every /health response in this process
# reports the same startup timestamp. ``launch_id`` is a short uuid so the
# launcher can tell "same process" from "restarted process" even if the
# git commit is unchanged.
_APP_STARTED_AT = datetime.now(timezone.utc).isoformat()
_APP_LAUNCH_ID = settings.APP_LAUNCH_ID or uuid4().hex[:12]


def app_build_info() -> dict:
    """Return the ``build`` block for /health.

    Kept as a function (not a module-level dict) so callers always see the
    current ``settings.APP_GIT_COMMIT`` value even if it is mutated after
    import (e.g. by tests).
    """
    return {
        "git_commit": settings.APP_GIT_COMMIT,
        "launch_id": _APP_LAUNCH_ID,
        "started_at": _APP_STARTED_AT,
    }
