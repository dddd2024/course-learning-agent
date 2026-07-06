"""Application configuration loaded from environment variables."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the course learning assistant backend.

    Values are read from environment variables, falling back to the
    defaults below. A ``.env`` file next to the application is also
    honoured.
    """

    DATABASE_URL: str = "sqlite:///./course_assistant.db"
    JWT_SECRET_KEY: str = "change_me"
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
    LLM_CONFIG_SECRET_KEY: str = "change-me-please"
    EMBEDDING_PROVIDER: str = "mock"
    MAX_UPLOAD_MB: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def upload_path(self) -> Path:
        return Path(self.UPLOAD_DIR)

    @property
    def parsed_path(self) -> Path:
        return Path(self.PARSED_DIR)


settings = Settings()
