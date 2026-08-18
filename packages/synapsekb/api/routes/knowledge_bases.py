from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import selectinload

from synapsekb.api.schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseOverview,
    KnowledgeBaseOverviewItem,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
    RecentDocumentOverviewItem,
)
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import knowledge_base_access_clause, require_admin
from synapsekb.database.models import (
    AuditLog,
    Document,
    KnowledgeBase,
    KnowledgeBaseMember,
    ProviderModel,
    User,
)
from synapsekb.models.provider import (
    create_provider,
    embedding_dimension_request_mode,
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
    model_id: uuid.UUID,
    dimensions: int,
) -> ProviderModel:
    await _validate_model(session, model_id, kind="embedding", label="Embedding")
    model = await session.get(ProviderModel, model_id)
    if model is None:
        raise HTTPException(status_code=422, detail="Embedding 模型不存在或不可用")
    supports_dimensions = embedding_dimension_request_mode(model) is not False
    if (
        not supports_dimensions
        and model.embedding_dimensions is not None
        and model.embedding_dimensions != dimensions
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"该 Embedding 模型输出维度固定为 {model.embedding_dimensions}，"
                f"知识库不能设置为 {dimensions} 维"
            ),
        )
    return model


async def _probe_embedding_dimensions(model: ProviderModel, dimensions: int) -> None:
    provider = create_provider(model, embedding_dimensions=dimensions)
    try:
        vectors = await provider.embeddings(["SynapseKB 知识库维度校验"])
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Embedding 模型连接或维度校验失败：{type(exc).__name__}: {str(exc)[:500]}",
        ) from exc
    finally:
        await provider.close()
    actual = len(vectors[0]) if vectors and vectors[0] else 0
    if actual != dimensions:
        raise HTTPException(
            status_code=422,
            detail=f"Embedding 模型实际返回 {actual} 维，与知识库选择的 {dimensions} 维不一致",
        )


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


@router.get("/overview", response_model=KnowledgeBaseOverview)
async def knowledge_base_overview(
    user: CurrentUser,
    session: DatabaseSession,
) -> KnowledgeBaseOverview:
    access = knowledge_base_access_clause(user)
    count_rows = (
        await session.execute(
            select(
                KnowledgeBase,
                func.count(Document.id).label("document_count"),
                func.count(
                    case((Document.status == "ready", Document.id), else_=None)
                ).label("ready_document_count"),
            )
            .outerjoin(Document, Document.knowledge_base_id == KnowledgeBase.id)
            .where(access)
            .group_by(KnowledgeBase.id)
            .order_by(KnowledgeBase.updated_at.desc())
        )
    ).all()
    recent_rows = (
        await session.execute(
            select(Document, KnowledgeBase.name)
            .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
            .where(access)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(10)
        )
    ).all()
    knowledge_bases = [
        KnowledgeBaseOverviewItem(
            id=item.id,
            name=item.name,
            description=item.description,
            document_count=int(document_count),
            ready_document_count=int(ready_document_count),
        )
        for item, document_count, ready_document_count in count_rows
    ]
    return KnowledgeBaseOverview(
        knowledge_bases=knowledge_bases,
        total_document_count=sum(item.document_count for item in knowledge_bases),
        recent_documents=[
            RecentDocumentOverviewItem(
                id=document.id,
                knowledge_base_id=document.knowledge_base_id,
                knowledge_base_name=knowledge_base_name,
                title=document.title,
                status=document.status,
                source_time=document.source_time,
                created_at=document.created_at,
            )
            for document, knowledge_base_name in recent_rows
        ],
    )


@router.post("", response_model=KnowledgeBaseRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> KnowledgeBase:
    require_admin(user)
    embedding_model = await _validate_embedding_model(
        session,
        payload.embedding_model_id,
        payload.embedding_dimensions,
    )
    await _probe_embedding_dimensions(embedding_model, payload.embedding_dimensions)
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
        embedding_dimensions=payload.embedding_dimensions,
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
        if payload.embedding_model_id is None:
            raise HTTPException(status_code=422, detail="知识库必须保留 Embedding 模型")
        if payload.embedding_model_id != knowledge_base.embedding_model_id:
            raise HTTPException(
                status_code=409,
                detail="Embedding 模型在知识库创建后已锁定；如需更换，请新建知识库并重新索引文档",
            )
    if (
        "embedding_dimensions" in supplied
        and payload.embedding_dimensions != knowledge_base.embedding_dimensions
    ):
        raise HTTPException(
            status_code=409,
            detail="Embedding 维度在知识库创建后已锁定；如需更换，请新建知识库并重新索引文档",
        )
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
