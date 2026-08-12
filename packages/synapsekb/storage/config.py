from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.auth.security import decrypt_secret
from synapsekb.config import Settings, get_settings
from synapsekb.database.models import SystemSetting

STORAGE_SETTING_KEY = "storage.object"
STORAGE_ACCESS_KEY_CONTEXT = "setting:storage.object:access_key"
STORAGE_SECRET_KEY_CONTEXT = "setting:storage.object:secret_key"


@dataclass(frozen=True, slots=True)
class StorageConfig:
    backend: Literal["local", "s3", "oss", "cos"]
    local_storage_path: str
    bucket: str
    endpoint: str | None
    internal_endpoint: str | None
    use_internal_endpoint: bool
    region: str
    access_key: str
    secret_key: str
    force_path_style: bool
    key_prefix: str
    source: str

    @property
    def service_endpoint(self) -> str | None:
        if self.use_internal_endpoint and self.internal_endpoint:
            return self.internal_endpoint
        return self.endpoint

    def object_key(self, key: str) -> str:
        clean_key = key.lstrip("/")
        prefix = self.key_prefix.strip("/")
        return f"{prefix}/{clean_key}" if prefix else clean_key


def storage_config_from_settings(settings: Settings | None = None) -> StorageConfig:
    cfg = settings or get_settings()
    config = StorageConfig(
        backend=cfg.storage_backend,
        local_storage_path=cfg.local_storage_path,
        bucket=cfg.storage_bucket,
        endpoint=cfg.storage_endpoint.rstrip("/") if cfg.storage_endpoint else None,
        internal_endpoint=None,
        use_internal_endpoint=False,
        region=cfg.storage_region,
        access_key=cfg.storage_access_key.get_secret_value(),
        secret_key=cfg.storage_secret_key.get_secret_value(),
        force_path_style=cfg.storage_force_path_style,
        key_prefix="",
        source="environment",
    )
    validate_storage_config(config, cfg)
    return config


def _decrypt(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return decrypt_secret(base64.urlsafe_b64decode(value), context=context)


async def load_storage_config(session: AsyncSession) -> StorageConfig:
    setting = await session.get(SystemSetting, STORAGE_SETTING_KEY)
    if setting is None:
        return storage_config_from_settings()
    value = setting.value
    backend = str(value.get("backend") or "local")
    if backend not in {"local", "s3", "oss", "cos"}:
        raise RuntimeError("对象存储后端配置无效")
    config = StorageConfig(
        backend=backend,  # type: ignore[arg-type]
        local_storage_path=str(value.get("local_storage_path") or "./data/storage"),
        bucket=str(value.get("bucket") or ""),
        endpoint=(str(value["endpoint"]).rstrip("/") if value.get("endpoint") else None),
        internal_endpoint=(
            str(value["internal_endpoint"]).rstrip("/") if value.get("internal_endpoint") else None
        ),
        use_internal_endpoint=bool(value.get("use_internal_endpoint", False)),
        region=str(value.get("region") or "auto"),
        access_key=_decrypt(
            value.get("encrypted_access_key"),
            STORAGE_ACCESS_KEY_CONTEXT,
        ),
        secret_key=_decrypt(
            value.get("encrypted_secret_key"),
            STORAGE_SECRET_KEY_CONTEXT,
        ),
        force_path_style=bool(value.get("force_path_style", backend == "s3")),
        key_prefix=str(value.get("key_prefix") or "").strip("/"),
        source="database",
    )
    validate_storage_config(config)
    return config


def validate_storage_config(
    config: StorageConfig,
    settings: Settings | None = None,
) -> None:
    cfg = settings or get_settings()
    if config.backend != "local":
        if not config.bucket or not config.endpoint:
            raise RuntimeError("对象存储 Bucket 和 Endpoint 未配置")
        if not config.access_key or not config.secret_key:
            raise RuntimeError("对象存储访问凭证未配置")
    if cfg.environment != "production":
        return
    if config.backend == "local":
        raise RuntimeError("生产环境不能使用本地文件存储")
    if not config.endpoint or not config.endpoint.startswith("https://"):
        raise RuntimeError("生产对象存储 Endpoint 必须使用 HTTPS")
    if config.internal_endpoint and not config.internal_endpoint.startswith("https://"):
        raise RuntimeError("生产对象存储内网 Endpoint 必须使用 HTTPS")
