from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env") if (REPO_ROOT / ".env").exists() else None,
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://imm:imm@localhost:5432/imm"
    session_secret: str = "dev-session-secret-change-me"
    operator_password: str = ""
    live_order_server_flag: bool = False
    web_origin: str = "http://localhost:3000"
    log_level: str = "INFO"
    integrations_secret_key: str = ""
    defaults_path: Path = Field(default=REPO_ROOT / "config" / "defaults.yaml")


@lru_cache
def get_settings() -> Settings:
    return Settings()
