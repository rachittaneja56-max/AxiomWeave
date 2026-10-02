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
    allow_registration: bool = False
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY", repr=False)
    openai_model: str = "gpt-6-luna"
    openai_utility_model: str = "gpt-5-nano"


@lru_cache
def get_settings() -> Settings:
    return Settings()
