"""Settings read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./datadash.db"))
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", "dev-only-secret-change-me-please"))
    token_minutes: int = field(default_factory=lambda: int(os.getenv("TOKEN_MINUTES", "720")))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
    )
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "./data")))
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "25")))
    max_rows: int = field(default_factory=lambda: int(os.getenv("MAX_ROWS", "200000")))
    max_cols: int = field(default_factory=lambda: int(os.getenv("MAX_COLS", "200")))
    max_datasets_per_user: int = field(default_factory=lambda: int(os.getenv("MAX_DATASETS_PER_USER", "20")))
    max_widgets: int = 20
    rate_limit_enabled: bool = field(default_factory=lambda: _bool("RATE_LIMIT_ENABLED", True))
    trust_proxy: bool = field(default_factory=lambda: _bool("TRUST_PROXY", False))  # read X-Real-IP set by nginx

    def validate_for_production(self) -> None:
        if self.env == "production" and (len(self.secret_key) < 32 or self.secret_key.startswith("dev-only")):
            raise RuntimeError("SECRET_KEY must be a random string of 32+ characters in production")


def get_settings() -> Settings:
    return Settings()
