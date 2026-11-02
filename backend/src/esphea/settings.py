"""Runtime settings, read from ``ESPHEA_*`` environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ESPHEA_", frozen=True)

    database_url: str = "postgresql+psycopg://esphea:esphea@localhost:5432/esphea"
    redis_url: str = "redis://localhost:6379/0"
    data_dir: Path = Path("./data")
    queue_name: str = "esphea-runs"
    job_timeout_seconds: int = 7 * 24 * 3600
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8090"]

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
