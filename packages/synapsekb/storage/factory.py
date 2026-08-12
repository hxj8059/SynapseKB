from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.config import Settings
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.storage.base import ObjectStorage
from synapsekb.storage.config import (
    StorageConfig,
    load_storage_config,
    storage_config_from_settings,
)
from synapsekb.storage.local import LocalObjectStorage
from synapsekb.storage.s3 import S3ObjectStorage


def create_storage(
    settings: Settings | None = None,
    *,
    config: StorageConfig | None = None,
) -> ObjectStorage:
    cfg = config or storage_config_from_settings(settings)
    if cfg.backend == "local":
        return LocalObjectStorage(cfg.local_storage_path)
    if not cfg.bucket or not cfg.service_endpoint or not cfg.access_key or not cfg.secret_key:
        raise RuntimeError("对象存储配置不完整")
    return S3ObjectStorage(cfg)


async def create_runtime_storage(session: AsyncSession | None = None) -> ObjectStorage:
    if session is not None:
        return create_storage(config=await load_storage_config(session))
    async with AsyncSessionFactory() as database_session:
        config = await load_storage_config(database_session)
    return create_storage(config=config)
