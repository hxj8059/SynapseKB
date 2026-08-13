from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, status
from openai import APIConnectionError, APIStatusError, APITimeoutError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from synapsekb.api.schemas import ModelCreate, ModelRead, ModelTestResponse, ModelUpdate
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import require_admin
from synapsekb.auth.security import decrypt_secret, encrypt_secret
from synapsekb.database.models import (
    Agent,
    AuditLog,
    KnowledgeBase,
    ProviderModel,
    WikiHealthJob,
    WikiUpdateJob,
)
from synapsekb.models.provider import (
    DeterministicMockProvider,
    create_provider,
    normalize_model_base_url,
    validate_model_transport,
)

router = APIRouter()

ACTIVE_JOB_STATUSES = {"queued", "running"}


def _safe_request_url(exc: Exception) -> str | None:
    request = getattr(exc, "request", None)
    url = getattr(request, "url", None)
    if url is None:
        return None
    parsed = urlsplit(str(url))
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.scheme else None


def _model_error_details(exc: Exception) -> dict[str, object]:
    details: dict[str, object] = {
        "error_type": type(exc).__name__,
        "message": "模型服务调用失败",
    }
    endpoint = _safe_request_url(exc)
    if endpoint:
        details["endpoint"] = endpoint

    if isinstance(exc, (APITimeoutError, httpx.TimeoutException, TimeoutError)):
        details["message"] = "连接模型服务超时，请检查 Base URL、网络和超时设置"
        return details
    if isinstance(exc, (APIConnectionError, httpx.NetworkError)):
        details["message"] = "无法连接模型服务，请检查 Base URL、DNS、防火墙和网络出口"
        return details

    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        details["http_status"] = status_code

    payload: object = getattr(exc, "body", None)
    if not isinstance(payload, dict) and response is not None:
        try:
            payload = response.json()
        except Exception:
            payload = None
    if isinstance(payload, dict):
        error = payload.get("error", payload)
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message")
            message_zh = error.get("message_zh")
            request_id = error.get("request_id") or payload.get("request_id")
            if code is not None:
                details["provider_code"] = str(code)[:120]
            if isinstance(message, str) and message:
                details["message"] = message[:1000]
            if isinstance(message_zh, str) and message_zh:
                details["message_zh"] = message_zh[:1000]
            if request_id is not None:
                details["provider_request_id"] = str(request_id)[:200]
    elif isinstance(exc, APIStatusError):
        details["message"] = f"模型服务返回 HTTP {exc.status_code}"
    return details


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
        base_url=normalize_model_base_url(payload.kind.value, str(payload.base_url)),
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
    try:
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
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="模型配置名称已存在") from exc
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
    if payload.provider is not None:
        model.provider = payload.provider
    if payload.base_url is not None:
        model.base_url = normalize_model_base_url(model.kind, str(payload.base_url))
    if payload.model_name is not None:
        model.model_name = payload.model_name
    if payload.timeout_seconds is not None:
        model.timeout_seconds = payload.timeout_seconds
    if payload.max_concurrency is not None:
        model.max_concurrency = payload.max_concurrency
    if payload.clear_embedding_dimensions:
        model.embedding_dimensions = None
    elif payload.embedding_dimensions is not None:
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
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="模型配置名称已存在") from exc
    await session.refresh(model)
    return _read(model)


async def _configured_references(
    session: DatabaseSession,
    model_id: uuid.UUID,
) -> list[str]:
    references: list[str] = []
    knowledge_bases = (
        await session.scalars(
            select(KnowledgeBase.name)
            .where(
                or_(
                    KnowledgeBase.embedding_model_id == model_id,
                    KnowledgeBase.rag_chat_model_id == model_id,
                    KnowledgeBase.rerank_model_id == model_id,
                    KnowledgeBase.wiki_chat_model_id == model_id,
                    KnowledgeBase.wiki_health_chat_model_id == model_id,
                )
            )
            .order_by(KnowledgeBase.name)
            .limit(6)
        )
    ).all()
    if knowledge_bases:
        references.append(f"知识库：{'、'.join(knowledge_bases)}")

    agents = (
        await session.scalars(
            select(Agent.name)
            .where(Agent.chat_model_id == model_id)
            .order_by(Agent.name)
            .limit(6)
        )
    ).all()
    if agents:
        references.append(f"Agent：{'、'.join(agents)}")

    active_update = await session.scalar(
        select(WikiUpdateJob.id).where(
            WikiUpdateJob.model_id == model_id,
            WikiUpdateJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    active_health = await session.scalar(
        select(WikiHealthJob.id).where(
            WikiHealthJob.model_id == model_id,
            WikiHealthJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    if active_update is not None or active_health is not None:
        references.append("进行中的 Wiki 任务")
    return references


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> None:
    require_admin(user)
    model = await session.get(ProviderModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    references = await _configured_references(session, model_id)
    if references:
        raise HTTPException(
            status_code=409,
            detail=f"模型仍被使用，请先解除绑定或停用相关任务：{'；'.join(references)}",
        )
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="model.delete",
            resource_type="model",
            resource_id=model.id,
            metadata_json={
                "name": model.name,
                "kind": model.kind,
                "provider": model.provider,
            },
            created_at=datetime.now(UTC),
        )
    )
    await session.delete(model)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="模型仍被其他资源使用，请刷新页面并解除绑定后重试",
        ) from exc


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
    started = time.perf_counter()
    details: dict[str, object]
    ok = True
    provider = None
    try:
        provider = create_provider(model)
        if model.kind == "embedding":
            vectors = await provider.embeddings(["SynapseKB 模型连接测试"])
            actual_dimensions = len(vectors[0])
            expected_dimensions = model.embedding_dimensions
            dimensions_match = (
                expected_dimensions is None or actual_dimensions == expected_dimensions
            )
            ok = dimensions_match
            details = {
                "embedding_dimensions": actual_dimensions,
                "configured_dimensions": expected_dimensions,
                "dimensions_match": dimensions_match,
            }
            if dimensions_match:
                details["message"] = (
                    f"连接成功；创建知识库时可锁定为 {actual_dimensions} 维"
                )
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
    except HTTPException:
        raise
    except Exception as exc:
        ok = False
        details = _model_error_details(exc)
    finally:
        if provider is not None:
            await provider.close()
    return ModelTestResponse(
        ok=ok,
        kind=model.kind,
        latency_ms=int((time.perf_counter() - started) * 1000),
        details=details,
    )
