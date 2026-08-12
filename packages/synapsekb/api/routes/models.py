from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from synapsekb.api.schemas import ModelCreate, ModelRead, ModelTestResponse, ModelUpdate
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import require_admin
from synapsekb.auth.security import decrypt_secret, encrypt_secret
from synapsekb.database.models import AuditLog, ProviderModel
from synapsekb.models.provider import (
    DeterministicMockProvider,
    create_provider,
    validate_model_transport,
)

router = APIRouter()


def _read(model: ProviderModel) -> ModelRead:
    data = ModelRead.model_validate(model)
    return data.model_copy(update={"has_api_key": model.encrypted_api_key is not None})


@router.get("", response_model=list[ModelRead])
async def list_models(user: CurrentUser, session: DatabaseSession) -> list[ModelRead]:
    require_admin(user)
    models = (await session.scalars(select(ProviderModel).order_by(ProviderModel.name))).all()
    return [_read(model) for model in models]


@router.post("", response_model=ModelRead, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> ModelRead:
    require_admin(user)
    try:
        validate_model_transport(payload.provider, str(payload.base_url))
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    model = ProviderModel(
        name=payload.name,
        kind=payload.kind.value,
        provider=payload.provider,
        base_url=str(payload.base_url).rstrip("/"),
        model_name=payload.model_name,
        encrypted_api_key=(
            encrypt_secret(payload.api_key, context=f"model:{payload.name}")
            if payload.api_key
            else None
        ),
        timeout_seconds=payload.timeout_seconds,
        max_concurrency=payload.max_concurrency,
        embedding_dimensions=payload.embedding_dimensions,
        config=payload.config,
    )
    session.add(model)
    await session.flush()
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="model.create",
            resource_type="model",
            resource_id=model.id,
            metadata_json={"kind": model.kind, "provider": model.provider},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return _read(model)


@router.patch("/{model_id}", response_model=ModelRead)
async def update_model(
    model_id: uuid.UUID,
    payload: ModelUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> ModelRead:
    require_admin(user)
    model = await session.get(ProviderModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    old_name = model.name
    new_name = payload.name or old_name
    if payload.clear_api_key:
        model.encrypted_api_key = None
    elif payload.api_key:
        model.encrypted_api_key = encrypt_secret(payload.api_key, context=f"model:{new_name}")
    elif new_name != old_name and model.encrypted_api_key:
        plain_key = decrypt_secret(model.encrypted_api_key, context=f"model:{old_name}")
        model.encrypted_api_key = encrypt_secret(plain_key, context=f"model:{new_name}")
    model.name = new_name
    if payload.base_url is not None:
        model.base_url = str(payload.base_url).rstrip("/")
    if payload.model_name is not None:
        model.model_name = payload.model_name
    if payload.timeout_seconds is not None:
        model.timeout_seconds = payload.timeout_seconds
    if payload.max_concurrency is not None:
        model.max_concurrency = payload.max_concurrency
    if payload.embedding_dimensions is not None:
        model.embedding_dimensions = payload.embedding_dimensions
    if payload.is_enabled is not None:
        model.is_enabled = payload.is_enabled
    if payload.config is not None:
        model.config = payload.config
    try:
        validate_model_transport(model.provider, model.base_url)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="model.update",
            resource_type="model",
            resource_id=model.id,
            metadata_json={
                "enabled": model.is_enabled,
                "api_key_changed": bool(payload.api_key or payload.clear_api_key),
            },
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    await session.refresh(model)
    return _read(model)


@router.post("/{model_id}/test", response_model=ModelTestResponse)
async def test_model(
    model_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> ModelTestResponse:
    require_admin(user)
    model = await session.get(ProviderModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    provider = create_provider(model)
    started = time.perf_counter()
    details: dict[str, object]
    ok = True
    try:
        if model.kind == "embedding":
            vectors = await provider.embeddings(["SynapseKB 模型连接测试"])
            actual_dimensions = len(vectors[0])
            expected_dimensions = model.embedding_dimensions
            ok = expected_dimensions is None or actual_dimensions == expected_dimensions
            details = {
                "embedding_dimensions": actual_dimensions,
                "configured_dimensions": expected_dimensions,
                "dimensions_match": ok,
            }
        elif model.kind == "chat":
            if isinstance(provider, DeterministicMockProvider):
                details = {"message": "Mock 只支持 Embedding 测试"}
                ok = False
            else:
                details = await provider.probe_chat_json()
                ok = bool(details["content_present"]) and details["finish_reason"] == "stop"
        elif model.kind == "rerank":
            if isinstance(provider, DeterministicMockProvider):
                details = {"message": "Mock 不支持 Rerank 测试"}
                ok = False
            else:
                ranking = await provider.rerank(
                    "知识库",
                    ["知识库检索", "天气预报"],
                    top_n=2,
                )
                details = {"ranking": ranking}
        else:
            raise HTTPException(status_code=422, detail="OCR 请使用独立 OCR 测试接口")
    finally:
        await provider.close()
    return ModelTestResponse(
        ok=ok,
        kind=model.kind,
        latency_ms=int((time.perf_counter() - started) * 1000),
        details=details,
    )
