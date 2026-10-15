"""Application configuration loaded from environment variables / .env."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://warranty:warranty_dev@localhost:5432/warranty_db"
    test_database_url: str | None = None
    jwt_secret: str = "insecure-development-secret"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    app_env: str = "development"
    demo_user_password: str = "demo1234"
    cors_origins: str = "http://localhost:5173"
    model_artifact_dir: str = "model_artifacts"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def artifact_path(self) -> Path:
        p = Path(self.model_artifact_dir)
        return p if p.is_absolute() else BACKEND_DIR / p

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
