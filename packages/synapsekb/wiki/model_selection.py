from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.database.models import (
    KnowledgeBase,
    ProviderModel,
    WikiHealthJob,
    WikiUpdateJob,
)


class WikiModelConfigurationError(RuntimeError):
    pass


async def validate_wiki_model(
    session: AsyncSession,
    model_id: uuid.UUID,
) -> ProviderModel:
    model = await session.get(ProviderModel, model_id)
    if model is None or model.kind != "chat" or not model.is_enabled:
        raise WikiModelConfigurationError("Wiki Chat 模型不存在、类型不正确或已停用")
    return model


async def resolve_wiki_model(
    session: AsyncSession,
    knowledge_base: KnowledgeBase,
    job: WikiUpdateJob | None = None,
) -> ProviderModel:
    """Resolve one auditable model instead of silently choosing the oldest model."""

    selected_id = (
        job.model_id
        if job is not None and job.model_id
        else knowledge_base.wiki_chat_model_id
    )
    if selected_id is not None:
        return await validate_wiki_model(session, selected_id)

    available = list(
        (
            await session.scalars(
                select(ProviderModel)
                .where(
                    ProviderModel.kind == "chat",
                    ProviderModel.is_enabled.is_(True),
                )
                .order_by(ProviderModel.created_at, ProviderModel.id)
                .limit(2)
            )
        ).all()
    )
    if not available:
        raise WikiModelConfigurationError("尚未配置可用的 Wiki Chat 模型")
    if len(available) > 1:
        raise WikiModelConfigurationError(
            "存在多个可用 Chat 模型，请在知识库的 Wiki 设置中明确选择一个模型"
        )
    return available[0]


async def resolve_wiki_health_model(
    session: AsyncSession,
    knowledge_base: KnowledgeBase,
    job: WikiHealthJob | None = None,
) -> ProviderModel:
    """Resolve the separately configured Wiki maintenance/review model."""

    selected_id = (
        job.model_id
        if job is not None and job.model_id
        else knowledge_base.wiki_health_chat_model_id
    )
    if selected_id is None:
        # Existing installations remain functional, while the UI exposes a
        # dedicated choice for new deployments.
        selected_id = knowledge_base.wiki_chat_model_id
    if selected_id is not None:
        return await validate_wiki_model(session, selected_id)
    raise WikiModelConfigurationError("请为知识库配置 Wiki 健康检查 Chat 模型")
