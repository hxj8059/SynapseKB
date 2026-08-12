from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "SynapseKB"
    api_prefix: str = "/api/v1"
    public_base_url: str = "http://localhost"
    default_timezone: str = "Asia/Shanghai"

    database_url: str = "postgresql+asyncpg://synapsekb:synapsekb@postgres:5432/synapsekb"
    database_pool_mode: Literal["pooled", "null"] = "pooled"
    redis_url: str = "redis://redis:6379/0"

    jwt_secret: SecretStr = SecretStr("development-only-change-me-at-least-32-bytes")
    jwt_issuer: str = "synapsekb"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    credential_master_key: SecretStr = SecretStr("")

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    trusted_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    mcp_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost"])
    mcp_rate_limit_per_minute: int = 60
    api_rate_limit_per_minute: int = 300
    auth_rate_limit_per_minute: int = 20
    trust_proxy_headers: bool = False

    storage_backend: Literal["local", "s3", "oss", "cos"] = "local"
    local_storage_path: str = "./data/storage"
    storage_bucket: str = "synapsekb"
    storage_endpoint: str | None = None
    storage_region: str = "auto"
    storage_access_key: SecretStr = SecretStr("")
    storage_secret_key: SecretStr = SecretStr("")
    storage_force_path_style: bool = True

    max_upload_bytes: int = 200 * 1024 * 1024
    allowed_url_ports: set[int] = Field(default_factory=lambda: {80, 443})

    embedding_dimensions: int = 1536
    retrieval_vector_candidates: int = 100
    retrieval_keyword_candidates: int = 100
    retrieval_rrf_k: int = 60

    wiki_health_scheduler_poll_seconds: int = 300

    paddleocr_base_url: str | None = None
    paddleocr_api_key: SecretStr = SecretStr("")
    paddleocr_max_concurrency: int = 2

    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    log_level: str = "INFO"

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters")
        return value

    def assert_production_safe(self) -> None:
        if self.environment != "production":
            return
        if "development-only" in self.jwt_secret.get_secret_value():
            raise RuntimeError("Production JWT_SECRET is not configured")
        if not self.credential_master_key.get_secret_value():
            raise RuntimeError("Production CREDENTIAL_MASTER_KEY is not configured")
        if not self.public_base_url.startswith("https://"):
            raise RuntimeError("Production PUBLIC_BASE_URL must use HTTPS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_production_safe()
    return settings
