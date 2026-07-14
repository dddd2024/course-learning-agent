"""Application configuration loaded from environment variables."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
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
    # SEC-V3-01: When True, allow private/localhost LLM endpoints in ALL
    # environments. Defaults to False so SSRF protection is always active.
    # The cloud metadata endpoint 169.254.169.254 is ALWAYS blocked.
    ALLOW_PRIVATE_LLM_ENDPOINTS: bool = False
    # Task C: project identity exposed by /api/v1/health so the Windows
    # launcher can verify port 8000 actually serves this backend.
    APP_NAME: str = "course-learning-agent"
    APP_VERSION: str = "1.0.0-rc.3"
    # Task D: build identity for /health. APP_GIT_COMMIT is injected by
    # start_windows.ps1 (via $env:APP_GIT_COMMIT = git rev-parse HEAD) so
    # the launcher can detect when port 8000 is held by a stale backend
    # running an older commit. APP_LAUNCH_ID is generated per-process.
    APP_GIT_COMMIT: str = ""
    APP_LAUNCH_ID: str = ""

    # V7.5.2-04: explicit E2E mirrors.  Playwright must provide these
    # variables in addition to the normal runtime names.  Requiring both
    # prevents a typo or inherited shell variable from silently pointing
    # the backend or parse worker at a developer database/storage tree.
    E2E_MODE: bool = False
    E2E_RUN_ID: str = ""
    E2E_DATABASE_URL: str = ""
    E2E_UPLOAD_DIR: str = ""
    E2E_PARSED_DIR: str = ""

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

    def validate_e2e_isolation(self) -> None:
        """Fail fast when an E2E process is not fully isolated.

        Both the API process and the persistent parse worker import this
        settings module.  Validation therefore protects the two processes
        before either can open a database or write an uploaded/parsed file.
        """
        if not self.E2E_MODE:
            return

        run_id = self.E2E_RUN_ID.strip()
        if not run_id or re.fullmatch(r"[A-Za-z0-9._-]+", run_id) is None:
            raise ValueError("E2E_MODE requires a safe, non-empty E2E_RUN_ID")

        required = {
            "E2E_DATABASE_URL": self.E2E_DATABASE_URL,
            "E2E_UPLOAD_DIR": self.E2E_UPLOAD_DIR,
            "E2E_PARSED_DIR": self.E2E_PARSED_DIR,
        }
        missing = sorted(name for name, value in required.items() if not value.strip())
        if missing:
            raise ValueError(f"E2E isolation variables are missing: {', '.join(missing)}")

        if self.DATABASE_URL != self.E2E_DATABASE_URL:
            raise ValueError("DATABASE_URL must exactly match E2E_DATABASE_URL in E2E_MODE")
        if Path(self.UPLOAD_DIR).resolve() != Path(self.E2E_UPLOAD_DIR).resolve():
            raise ValueError("UPLOAD_DIR must exactly match E2E_UPLOAD_DIR in E2E_MODE")
        if Path(self.PARSED_DIR).resolve() != Path(self.E2E_PARSED_DIR).resolve():
            raise ValueError("PARSED_DIR must exactly match E2E_PARSED_DIR in E2E_MODE")

        sqlite_prefix = "sqlite:///"
        if not self.DATABASE_URL.startswith(sqlite_prefix):
            raise ValueError("E2E_MODE currently requires a dedicated SQLite database")
        database_path = _sqlite_database_path(self.DATABASE_URL)

        def belongs_to_run(path: Path) -> bool:
            parts = {part.lower() for part in path.resolve().parts}
            # The allocator defaults to a system temporary directory, while
            # older CI callers may still use .e2e-runs.  In both cases the
            # path must visibly belong to this exact run and never normal
            # uploads/parsed storage.
            return run_id.lower() in parts and (
                ".e2e-runs" in parts or "course-learning-agent-e2e" in parts
            )

        protected_paths = {
            "database": database_path,
            "uploads": Path(self.UPLOAD_DIR),
            "parsed": Path(self.PARSED_DIR),
        }
        outside = [name for name, path in protected_paths.items() if not belongs_to_run(path)]
        if outside:
            raise ValueError(
                "E2E paths must live under .e2e-runs or a system isolated run root containing E2E_RUN_ID: "
                + ", ".join(outside)
            )


def _sqlite_database_path(database_url: str) -> Path:
    """Resolve a SQLite URL to its filesystem path without depending on CWD.

    Hashing ``Path(database_url)`` is incorrect because the ``sqlite:///``
    scheme is treated as a relative filename.  The API and worker start from
    different directories, which previously produced different E2E runtime
    fingerprints for the same database.
    """
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("database URL must use sqlite:///")
    return Path(database_url[len(prefix):]).resolve()


def _runtime_path_fingerprint(path: Path | str) -> str:
    return hashlib.sha256(str(Path(path).resolve()).encode("utf-8")).hexdigest()


settings = Settings()
settings.validate_e2e_isolation()

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


def e2e_runtime_info() -> dict | None:
    """Return non-sensitive identity data for E2E API/worker handshake."""
    if not settings.E2E_MODE:
        return None
    return {
        "run_id": settings.E2E_RUN_ID,
        "database_fingerprint": _runtime_path_fingerprint(
            _sqlite_database_path(settings.DATABASE_URL)
        ),
        "upload_dir_fingerprint": _runtime_path_fingerprint(settings.UPLOAD_DIR),
        "parsed_dir_fingerprint": _runtime_path_fingerprint(settings.PARSED_DIR),
    }
