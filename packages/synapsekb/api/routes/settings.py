from __future__ import annotations

import base64
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, HTTPException, UploadFile

from synapsekb.api.schemas import (
    OcrSettingsRead,
    OcrSettingsUpdate,
    OcrTestResponse,
    StorageSettingsRead,
    StorageSettingsUpdate,
    StorageTestResponse,
)
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import require_admin
from synapsekb.auth.security import encrypt_secret
from synapsekb.database.models import AuditLog, SystemSetting
from synapsekb.document_processing.ocr_config import (
    OCR_SECRET_CONTEXT,
    OCR_SETTING_KEY,
    load_paddle_ocr_config,
)
from synapsekb.document_processing.paddleocr import PaddleOcrCloudClient
from synapsekb.document_processing.validation import validate_upload
from synapsekb.storage.config import (
    STORAGE_ACCESS_KEY_CONTEXT,
    STORAGE_SECRET_KEY_CONTEXT,
    STORAGE_SETTING_KEY,
    load_storage_config,
)
from synapsekb.storage.errors import describe_storage_error
from synapsekb.storage.factory import create_storage

router = APIRouter()
OCR_TEST_MAX_BYTES = 20 * 1024 * 1024
OCR_TEST_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}


@router.get("/ocr", response_model=OcrSettingsRead)
async def get_ocr_settings(
    user: CurrentUser,
    session: DatabaseSession,
) -> OcrSettingsRead:
    require_admin(user)
    config = await load_paddle_ocr_config(session)
    return OcrSettingsRead(
        base_url=config.base_url,
        default_model=config.default_model,
        timeout_seconds=config.timeout_seconds,
        max_concurrency=config.max_concurrency,
        has_api_key=bool(config.api_key),
        source=config.source,
    )


@router.put("/ocr", response_model=OcrSettingsRead)
async def update_ocr_settings(
    payload: OcrSettingsUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> OcrSettingsRead:
    require_admin(user)
    setting = await session.get(SystemSetting, OCR_SETTING_KEY)
    value = dict(setting.value) if setting is not None else {}
    encrypted = value.get("encrypted_api_key")
    if payload.clear_api_key:
        encrypted = None
    elif payload.api_key:
        encrypted = base64.urlsafe_b64encode(
            encrypt_secret(payload.api_key, context=OCR_SECRET_CONTEXT)
        ).decode()
    elif setting is None:
        inherited = await load_paddle_ocr_config(session)
        if inherited.api_key:
            encrypted = base64.urlsafe_b64encode(
                encrypt_secret(inherited.api_key, context=OCR_SECRET_CONTEXT)
            ).decode()
    value = {
        "base_url": str(payload.base_url).rstrip("/") if payload.base_url else None,
        "default_model": payload.default_model,
        "timeout_seconds": payload.timeout_seconds,
        "max_concurrency": payload.max_concurrency,
        "encrypted_api_key": encrypted,
    }
    if setting is None:
        setting = SystemSetting(
            key=OCR_SETTING_KEY,
            value=value,
            updated_by_id=user.id,
        )
        session.add(setting)
    else:
        setting.value = value
        setting.updated_by_id = user.id
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="settings.ocr.update",
            resource_type="system_setting",
            metadata_json={
                "default_model": payload.default_model,
                "max_concurrency": payload.max_concurrency,
                "api_key_changed": bool(payload.api_key or payload.clear_api_key),
            },
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return await get_ocr_settings(user, session)


@router.post("/ocr/test", response_model=OcrTestResponse)
async def test_ocr_settings(
    user: CurrentUser,
    session: DatabaseSession,
    file: UploadFile = File(...),
) -> OcrTestResponse:
    require_admin(user)
    config = await load_paddle_ocr_config(session)
    if not config.api_key:
        raise HTTPException(status_code=409, detail="尚未配置 PaddleOCR Access Token")
    filename = file.filename or "ocr-test.pdf"
    suffix = Path(filename).suffix.lower()
    if suffix not in OCR_TEST_SUFFIXES:
        raise HTTPException(status_code=422, detail="OCR 测试仅支持 PDF 和图片")
    with tempfile.TemporaryDirectory(prefix="synapsekb-ocr-test-") as temp_dir:
        path = Path(temp_dir) / Path(filename).name
        size = 0
        first_bytes = b""
        async with aiofiles.open(path, "wb") as handle:
            while chunk := await file.read(1024 * 1024):
                if not first_bytes:
                    first_bytes = chunk[:32]
                size += len(chunk)
                if size > OCR_TEST_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="OCR 测试文件不能超过 20 MB")
                await handle.write(chunk)
        try:
            validate_upload(filename, file.content_type or "application/octet-stream", first_bytes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        client = PaddleOcrCloudClient(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout_seconds=config.timeout_seconds,
        )
        try:
            task_id = await client.submit(path, model=config.default_model)
            result = await client.wait(
                task_id,
                model=config.default_model,
                timeout_seconds=config.timeout_seconds,
            )
        finally:
            await client.close()
    return OcrTestResponse(
        ok=True,
        task_id=result.task_id,
        page_count=result.page_count,
        markdown_preview=result.markdown[:500],
        metadata=result.metadata,
    )


def _encrypted_setting_secret(
    *,
    new_value: str | None,
    clear: bool,
    inherited: str,
    existing: object,
    context: str,
) -> str | None:
    if clear:
        return None
    if new_value:
        return base64.urlsafe_b64encode(encrypt_secret(new_value, context=context)).decode()
    if isinstance(existing, str) and existing:
        return existing
    if inherited:
        return base64.urlsafe_b64encode(encrypt_secret(inherited, context=context)).decode()
    return None


@router.get("/storage", response_model=StorageSettingsRead)
async def get_storage_settings(
    user: CurrentUser,
    session: DatabaseSession,
) -> StorageSettingsRead:
    require_admin(user)
    config = await load_storage_config(session)
    return StorageSettingsRead(
        backend=config.backend,
        local_storage_path=config.local_storage_path,
        bucket=config.bucket,
        endpoint=config.endpoint,
        internal_endpoint=config.internal_endpoint,
        use_internal_endpoint=config.use_internal_endpoint,
        region=config.region,
        force_path_style=config.force_path_style,
        key_prefix=config.key_prefix,
        has_access_key=bool(config.access_key),
        has_secret_key=bool(config.secret_key),
        source=config.source,
    )


@router.put("/storage", response_model=StorageSettingsRead)
async def update_storage_settings(
    payload: StorageSettingsUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> StorageSettingsRead:
    require_admin(user)
    if payload.backend != "local" and (payload.endpoint is None or not payload.bucket):
        raise HTTPException(status_code=422, detail="对象存储需要 Endpoint 和 Bucket")
    if (
        payload.backend == "cos"
        and payload.endpoint is not None
        and payload.endpoint.host
        and payload.endpoint.host.startswith(f"{payload.bucket}.")
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "腾讯云 COS Endpoint 应填写不含 Bucket 名称的服务地址，"
                "例如 https://cos.ap-shanghai.myqcloud.com"
            ),
        )
    from synapsekb.config import get_settings

    if get_settings().environment == "production":
        if payload.backend == "local":
            raise HTTPException(status_code=422, detail="生产环境不能使用本地存储")
        if payload.endpoint is None or payload.endpoint.scheme != "https":
            raise HTTPException(status_code=422, detail="生产对象存储 Endpoint 必须使用 HTTPS")
        if payload.internal_endpoint is not None and payload.internal_endpoint.scheme != "https":
            raise HTTPException(status_code=422, detail="生产内网 Endpoint 必须使用 HTTPS")

    setting = await session.get(SystemSetting, STORAGE_SETTING_KEY)
    existing = dict(setting.value) if setting is not None else {}
    inherited = await load_storage_config(session)
    value = {
        "backend": payload.backend,
        "local_storage_path": payload.local_storage_path,
        "bucket": payload.bucket,
        "endpoint": str(payload.endpoint).rstrip("/") if payload.endpoint else None,
        "internal_endpoint": (
            str(payload.internal_endpoint).rstrip("/") if payload.internal_endpoint else None
        ),
        "use_internal_endpoint": payload.use_internal_endpoint,
        "region": payload.region,
        "force_path_style": payload.force_path_style,
        "key_prefix": payload.key_prefix,
        "encrypted_access_key": _encrypted_setting_secret(
            new_value=payload.access_key,
            clear=payload.clear_access_key,
            inherited=inherited.access_key,
            existing=existing.get("encrypted_access_key"),
            context=STORAGE_ACCESS_KEY_CONTEXT,
        ),
        "encrypted_secret_key": _encrypted_setting_secret(
            new_value=payload.secret_key,
            clear=payload.clear_secret_key,
            inherited=inherited.secret_key,
            existing=existing.get("encrypted_secret_key"),
            context=STORAGE_SECRET_KEY_CONTEXT,
        ),
    }
    if payload.backend != "local" and (
        not value["encrypted_access_key"] or not value["encrypted_secret_key"]
    ):
        raise HTTPException(status_code=422, detail="对象存储需要 Access Key 和 Secret Key")
    if setting is None:
        setting = SystemSetting(
            key=STORAGE_SETTING_KEY,
            value=value,
            updated_by_id=user.id,
        )
        session.add(setting)
    else:
        setting.value = value
        setting.updated_by_id = user.id
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="settings.storage.update",
            resource_type="system_setting",
            metadata_json={
                "backend": payload.backend,
                "bucket": payload.bucket,
                "key_prefix": payload.key_prefix,
                "access_key_changed": bool(payload.access_key or payload.clear_access_key),
                "secret_key_changed": bool(payload.secret_key or payload.clear_secret_key),
            },
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return await get_storage_settings(user, session)


@router.post("/storage/test", response_model=StorageTestResponse)
async def test_storage_settings(
    user: CurrentUser,
    session: DatabaseSession,
) -> StorageTestResponse:
    require_admin(user)
    config = await load_storage_config(session)
    storage = create_storage(config=config)
    key = f"_connection-tests/{uuid.uuid4()}.txt"
    started = time.perf_counter()
    stage = "准备连接测试"
    uploaded = False
    operation_error: Exception | None = None
    cleanup_error: Exception | None = None
    presigned: str | None = None
    with tempfile.TemporaryDirectory(prefix="synapsekb-storage-test-") as temp_dir:
        path = Path(temp_dir) / "probe.txt"
        async with aiofiles.open(path, "wb") as handle:
            await handle.write(b"SynapseKB object storage connection test")
        try:
            stage = "写入测试对象"
            await storage.put_file(key, path, "text/plain")
            uploaded = True
            stage = "检查测试对象"
            if not await storage.exists(key):
                raise HTTPException(status_code=502, detail="写入后无法读取测试对象")
            stage = "读取测试对象"
            content = await storage.read(key)
            if content != b"SynapseKB object storage connection test":
                raise HTTPException(status_code=502, detail="对象存储测试内容不一致")
            stage = "生成浏览器预签名地址"
            presigned = await storage.presign_upload(
                f"_connection-tests/{uuid.uuid4()}.txt",
                "text/plain",
                60,
            )
        except Exception as exc:  # converted below after cleanup
            operation_error = exc
        finally:
            if uploaded:
                try:
                    await storage.delete(key)
                except Exception as exc:  # report cleanup without hiding the primary failure
                    cleanup_error = exc
    if operation_error is not None:
        if isinstance(operation_error, HTTPException):
            raise operation_error
        error_detail = describe_storage_error(operation_error, backend=config.backend)
        raise HTTPException(
            status_code=502,
            detail=f"对象存储{stage}失败：{error_detail}",
        ) from operation_error
    if cleanup_error is not None:
        raise HTTPException(
            status_code=502,
            detail=(
                "对象存储读写成功，但清理测试对象失败："
                f"{describe_storage_error(cleanup_error, backend=config.backend)}"
            ),
        ) from cleanup_error
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="settings.storage.test",
            resource_type="system_setting",
            metadata_json={"backend": config.backend, "bucket": config.bucket, "ok": True},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return StorageTestResponse(
        ok=True,
        backend=config.backend,
        bucket=config.bucket,
        latency_ms=int((time.perf_counter() - started) * 1000),
        presigned_upload_supported=bool(presigned),
    )
