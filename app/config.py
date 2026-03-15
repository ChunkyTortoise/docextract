from __future__ import annotations

import json
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/docextract"
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    api_key_secret: str = "change-me-32-chars-minimum-secret"

    # Storage
    storage_backend: str = "local"  # "local" or "r2"
    storage_local_path: str = "./storage/local"
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "docextract"

    # Encryption
    aes_key: str = ""  # base64-encoded 32-byte key for AES-GCM

    # API
    cors_origins: List[str] = ["http://localhost:8501"]
    log_level: str = "INFO"

    # Processing limits
    max_file_size_mb: int = 50
    max_pages: int = 100
    ocr_engine: str = "tesseract"  # "tesseract" or "paddle"

    # Worker
    worker_queue: str = "docextract"
    worker_max_jobs: int = 10
    job_timeout_seconds: int = 300

    # Extraction
    extraction_confidence_threshold: float = 0.8

    # Environment
    environment: str = "development"

    # Demo mode
    demo_mode: bool = False
    demo_api_key: str = "demo-key-docextract-2026"

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        # Render (and Heroku) provide postgres:// or postgresql:// — both need asyncpg driver
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @model_validator(mode='after')
    def validate_production_secrets(self) -> 'Settings':
        if self.environment != "development":
            if self.api_key_secret == "change-me-32-chars-minimum-secret":
                raise ValueError(
                    "api_key_secret must be changed from the default value in non-development environments"
                )
        return self

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
