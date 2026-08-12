from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from synapsekb.api.schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
)
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import knowledge_base_access_clause, require_admin
from synapsekb.database.models import (
    AuditLog,
    KnowledgeBase,
    KnowledgeBaseMember,
    ProviderModel,
    User,
)

router = APIRouter()


async def _validate_model(
    session: DatabaseSession,
    model_id: uuid.UUID | None,
    *,
    kind: str,
    label: str,
) -> None:
    if model_id is None:
        return
    model = await session.get(ProviderModel, model_id)
    if model is None or model.kind != kind or not model.is_enabled:
        raise HTTPException(status_code=422, detail=f"{label} 模型不存在或不可用")


async def _validate_embedding_model(
    session: DatabaseSession,
    model_id: uuid.UUID | None,
) -> None:
    await _validate_model(session, model_id, kind="embedding", label="Embedding")


async def _validate_chat_model(
    session: DatabaseSession,
    model_id: uuid.UUID | None,
    *,
    label: str,
) -> None:
    await _validate_model(session, model_id, kind="chat", label=label)


async def _validate_rerank_model(
    session: DatabaseSession,
    model_id: uuid.UUID | None,
) -> None:
    await _validate_model(session, model_id, kind="rerank", label="Rerank")


async def _validate_member_ids(
    session: DatabaseSession,
    member_ids: list[uuid.UUID],
) -> None:
    requested = set(member_ids)
    if not requested:
        return
    existing = set(
        (
            await session.scalars(
                select(User.id).where(User.id.in_(requested), User.is_active.is_(True))
            )
        ).all()
    )
    if existing != requested:
        raise HTTPException(status_code=422, detail="包含不存在或已停用的知识库成员")


@router.get("", response_model=list[KnowledgeBaseRead])
async def list_knowledge_bases(
    user: CurrentUser,
    session: DatabaseSession,
) -> list[KnowledgeBase]:
    query = (
        select(KnowledgeBase)
        .where(knowledge_base_access_clause(user))
        .order_by(KnowledgeBase.updated_at.desc())
    )
    return list((await session.scalars(query)).all())


@router.post("", response_model=KnowledgeBaseRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> KnowledgeBase:
    require_admin(user)
    await _validate_embedding_model(session, payload.embedding_model_id)
    await _validate_chat_model(session, payload.rag_chat_model_id, label="RAG Chat")
    await _validate_rerank_model(session, payload.rerank_model_id)
    await _validate_chat_model(session, payload.wiki_chat_model_id, label="Wiki 生成 Chat")
    await _validate_chat_model(
        session,
        payload.wiki_health_chat_model_id,
        label="Wiki 健康检查 Chat",
    )
    await _validate_member_ids(session, payload.member_ids)
    knowledge_base = KnowledgeBase(
        name=payload.name,
        description=payload.description,
        visibility=payload.visibility,
        embedding_model_id=payload.embedding_model_id,
        rag_chat_model_id=payload.rag_chat_model_id,
        rerank_model_id=payload.rerank_model_id,
        rag_max_output_tokens=payload.rag_max_output_tokens,
        wiki_chat_model_id=payload.wiki_chat_model_id,
        wiki_health_chat_model_id=payload.wiki_health_chat_model_id,
        wiki_enabled=payload.wiki_enabled,
        wiki_health_check_enabled=payload.wiki_health_check_enabled,
        wiki_health_check_interval_hours=payload.wiki_health_check_interval_hours,
        wiki_node_types=payload.wiki_node_types,
        wiki_generation_prompt=payload.wiki_generation_prompt,
        created_by_id=user.id,
    )
    session.add(knowledge_base)
    await session.flush()
    for member_id in set(payload.member_ids):
        session.add(
            KnowledgeBaseMember(
                knowledge_base_id=knowledge_base.id,
                user_id=member_id,
                created_at=datetime.now(UTC),
            )
        )
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="knowledge_base.create",
            resource_type="knowledge_base",
            resource_id=knowledge_base.id,
            metadata_json={"visibility": knowledge_base.visibility},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    await session.refresh(knowledge_base)
    return knowledge_base


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseRead)
async def get_knowledge_base(
    knowledge_base_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> KnowledgeBase:
    query = (
        select(KnowledgeBase)
        .options(selectinload(KnowledgeBase.members))
        .where(
            KnowledgeBase.id == knowledge_base_id,
            knowledge_base_access_clause(user),
        )
    )
    knowledge_base = await session.scalar(query)
    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="知识库不存在或无权访问")
    return knowledge_base


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseRead)
async def update_knowledge_base(
    knowledge_base_id: uuid.UUID,
    payload: KnowledgeBaseUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> KnowledgeBase:
    require_admin(user)
    knowledge_base = await session.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    supplied = payload.model_fields_set
    if "name" in supplied and payload.name is not None:
        knowledge_base.name = payload.name
    if "description" in supplied and payload.description is not None:
        knowledge_base.description = payload.description
    if "visibility" in supplied and payload.visibility is not None:
        knowledge_base.visibility = payload.visibility
    if "wiki_enabled" in supplied and payload.wiki_enabled is not None:
        knowledge_base.wiki_enabled = payload.wiki_enabled
    if (
        "wiki_health_check_enabled" in supplied
        and payload.wiki_health_check_enabled is not None
    ):
        knowledge_base.wiki_health_check_enabled = payload.wiki_health_check_enabled
    if (
        "wiki_health_check_interval_hours" in supplied
        and payload.wiki_health_check_interval_hours is not None
    ):
        knowledge_base.wiki_health_check_interval_hours = (
            payload.wiki_health_check_interval_hours
        )
    if "wiki_node_types" in supplied and payload.wiki_node_types is not None:
        knowledge_base.wiki_node_types = payload.wiki_node_types
    if "wiki_generation_prompt" in supplied and payload.wiki_generation_prompt is not None:
        knowledge_base.wiki_generation_prompt = payload.wiki_generation_prompt
    if "embedding_model_id" in supplied:
        await _validate_embedding_model(session, payload.embedding_model_id)
        knowledge_base.embedding_model_id = payload.embedding_model_id
    if "rag_chat_model_id" in supplied:
        await _validate_chat_model(session, payload.rag_chat_model_id, label="RAG Chat")
        knowledge_base.rag_chat_model_id = payload.rag_chat_model_id
    if "rerank_model_id" in supplied:
        await _validate_rerank_model(session, payload.rerank_model_id)
        knowledge_base.rerank_model_id = payload.rerank_model_id
    if "rag_max_output_tokens" in supplied and payload.rag_max_output_tokens is not None:
        knowledge_base.rag_max_output_tokens = payload.rag_max_output_tokens
    if "wiki_chat_model_id" in supplied:
        await _validate_chat_model(
            session,
            payload.wiki_chat_model_id,
            label="Wiki 生成 Chat",
        )
        knowledge_base.wiki_chat_model_id = payload.wiki_chat_model_id
    if "wiki_health_chat_model_id" in supplied:
        await _validate_chat_model(
            session,
            payload.wiki_health_chat_model_id,
            label="Wiki 健康检查 Chat",
        )
        knowledge_base.wiki_health_chat_model_id = payload.wiki_health_chat_model_id
    if payload.member_ids is not None:
        await _validate_member_ids(session, payload.member_ids)
        await session.execute(
            delete(KnowledgeBaseMember).where(
                KnowledgeBaseMember.knowledge_base_id == knowledge_base.id
            )
        )
        session.add_all(
            [
                KnowledgeBaseMember(
                    knowledge_base_id=knowledge_base.id,
                    user_id=member_id,
                    created_at=datetime.now(UTC),
                )
                for member_id in set(payload.member_ids)
            ]
        )
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="knowledge_base.update",
            resource_type="knowledge_base",
            resource_id=knowledge_base.id,
            metadata_json={"fields": sorted(supplied)},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    await session.refresh(knowledge_base)
    return knowledge_base
