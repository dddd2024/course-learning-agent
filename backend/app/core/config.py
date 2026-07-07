"""Application configuration loaded from environment variables."""
from pathlib import Path

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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    UPLOAD_DIR: str = "../storage/uploads"
    PARSED_DIR: str = "../storage/parsed"
    LLM_PROVIDER: str = "mock"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = ""
    LLM_TIMEOUT_SECONDS: int = 60
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
