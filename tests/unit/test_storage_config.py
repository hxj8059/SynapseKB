import pytest
from pydantic import ValidationError
from synapsekb.api.schemas import StorageSettingsUpdate
from synapsekb.config import Settings
from synapsekb.storage.config import StorageConfig, validate_storage_config
from synapsekb.storage.s3 import S3ObjectStorage


def _oss_config() -> StorageConfig:
    return StorageConfig(
        backend="oss",
        local_storage_path="./data/storage",
        bucket="example",
        endpoint="https://oss-cn-shanghai.aliyuncs.com",
        internal_endpoint="https://oss-cn-shanghai-internal.aliyuncs.com",
        use_internal_endpoint=True,
        region="cn-shanghai",
        access_key="access",
        secret_key="unit-test-only",  # noqa: S106
        force_path_style=False,
        key_prefix="SynapseKB",
        source="database",
    )


def test_storage_config_applies_prefix_and_internal_endpoint() -> None:
    config = _oss_config()
    assert config.object_key("originals/document.pdf") == "SynapseKB/originals/document.pdf"
    assert config.service_endpoint == "https://oss-cn-shanghai-internal.aliyuncs.com"


def test_oss_client_disables_unsupported_streaming_checksum() -> None:
    storage = S3ObjectStorage(_oss_config())
    botocore_config = storage.options["config"]
    assert botocore_config.request_checksum_calculation == "when_required"
    assert botocore_config.response_checksum_validation == "when_required"
    assert botocore_config.s3["addressing_style"] == "virtual"
    assert botocore_config.s3["payload_signing_enabled"] is False


def test_storage_settings_reject_unsafe_prefix() -> None:
    with pytest.raises(ValidationError):
        StorageSettingsUpdate(
            backend="oss",
            bucket="example",
            endpoint="https://oss-cn-shanghai.aliyuncs.com",
            key_prefix="../outside",
        )


def _production_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="production",
        jwt_secret="production-test-secret-at-least-32-characters",  # noqa: S106
        credential_master_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        public_base_url="https://synapsekb.example.com",
        storage_backend="local",
        storage_access_key="",
        storage_secret_key="",
    )


def test_production_accepts_database_storage_without_env_secret_duplicate() -> None:
    validate_storage_config(_oss_config(), _production_settings())


def test_production_rejects_local_runtime_storage() -> None:
    config = _oss_config()
    local = StorageConfig(
        backend="local",
        local_storage_path=config.local_storage_path,
        bucket="",
        endpoint=None,
        internal_endpoint=None,
        use_internal_endpoint=False,
        region="auto",
        access_key="",
        secret_key="",
        force_path_style=True,
        key_prefix="",
        source="database",
    )
    with pytest.raises(RuntimeError, match="本地文件存储"):
        validate_storage_config(local, _production_settings())
