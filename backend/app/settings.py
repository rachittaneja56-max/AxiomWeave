from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SIH_",
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "sqlite:///./axiomweave.db"
    private_asset_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / ".private-assets"
    )
    private_asset_backend: str = "local"
    s3_bucket: str | None = None
    s3_endpoint: str | None = None
    s3_region: str | None = None
    allow_registration: bool = False
    allowed_frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_enabled: bool = True
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY", repr=False)
    openai_model: str = "gpt-6-luna"
    openai_utility_model: str = "gpt-5-nano"
    openai_action_model: str | None = None
    openai_evidence_model: str | None = None
    openai_consistency_model: str | None = None
    openai_ocr_model: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
