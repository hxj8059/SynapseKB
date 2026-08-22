from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

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
    allow_insecure_http: bool = False
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
    mcp_allow_null_origin: bool = False
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

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("PUBLIC_BASE_URL must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("PUBLIC_BASE_URL cannot contain credentials, query, or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError("PUBLIC_BASE_URL cannot contain a path")
        return normalized

    @property
    def public_origin(self) -> str:
        parsed = urlsplit(self.public_base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def public_host(self) -> str:
        return urlsplit(self.public_base_url).hostname or "localhost"

    @property
    def secure_cookies(self) -> bool:
        return urlsplit(self.public_base_url).scheme == "https"

    @property
    def effective_cors_origins(self) -> list[str]:
        return _unique_origins([*self.cors_origins, self.public_origin])

    @property
    def effective_trusted_hosts(self) -> list[str]:
        return list(dict.fromkeys([*self.trusted_hosts, self.public_host]))

    @property
    def effective_mcp_allowed_origins(self) -> list[str]:
        origins = _unique_origins([*self.mcp_allowed_origins, self.public_origin])
        if self.mcp_allow_null_origin:
            origins.append("null")
        return origins

    @property
    def mcp_transport_allowed_hosts(self) -> list[str]:
        allowed: list[str] = []
        for host in self.effective_trusted_hosts:
            if host == "*":
                continue
            allowed.append(host)
            if ":" not in host and not host.startswith("["):
                allowed.append(f"{host}:*")
        return list(dict.fromkeys(allowed))

    @property
    def mcp_transport_allowed_origins(self) -> list[str]:
        allowed: list[str] = []
        for origin in self.effective_mcp_allowed_origins:
            allowed.append(origin)
            if origin != "null" and urlsplit(origin).port is None:
                allowed.append(f"{origin}:*")
        return list(dict.fromkeys(allowed))

    def assert_production_safe(self) -> None:
        if self.environment != "production":
            return
        if "development-only" in self.jwt_secret.get_secret_value():
            raise RuntimeError("Production JWT_SECRET is not configured")
        if not self.credential_master_key.get_secret_value():
            raise RuntimeError("Production CREDENTIAL_MASTER_KEY is not configured")
        if not self.secure_cookies and not self.allow_insecure_http:
            raise RuntimeError(
                "Production PUBLIC_BASE_URL must use HTTPS unless ALLOW_INSECURE_HTTP=true"
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_production_safe()
    return settings


def _unique_origins(values: list[str]) -> list[str]:
    origins: list[str] = []
    for value in values:
        normalized = value.strip().rstrip("/")
        if normalized and normalized not in origins:
            origins.append(normalized)
    return origins
