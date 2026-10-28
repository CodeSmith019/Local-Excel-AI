import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and dotenv files."""

    model_config = SettingsConfigDict(
        env_prefix="EXAI_",
        env_file=os.getenv("EXAI_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "local-model"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 512
    llm_timeout_s: int = 120
    llm_extra_body: dict[str, Any] = Field(default_factory=dict)
    machine_name: str = "dev"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    data_dir: Path = Path("data")
    max_retries: int = 2
    max_prompt_rows: int = 30


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
