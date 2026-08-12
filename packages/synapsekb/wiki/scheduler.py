from __future__ import annotations

import uuid

from sqlalchemy import func, select

from apps.wiki_worker.actors import generate_wiki
from synapsekb.database.models import KnowledgeBase, WikiSpace, WikiUpdateJob
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.wiki.model_selection import WikiModelConfigurationError, resolve_wiki_model

WIKI_INCREMENTAL_DOCUMENT_BATCH_SIZE = 20


async def schedule_wiki_update(
    knowledge_base_id: uuid.UUID,
    document_id: uuid.UUID,
) -> None:
    """Coalesce updates into the newest queued job for one published Wiki."""

    async with AsyncSessionFactory() as session:
        space = await session.scalar(
            select(WikiSpace).where(
                WikiSpace.knowledge_base_id == knowledge_base_id,
                WikiSpace.published_version.is_not(None),
            )
        )
        if space is None:
            return
        queued = await session.scalar(
            select(WikiUpdateJob)
            .where(
                WikiUpdateJob.space_id == space.id,
                WikiUpdateJob.status == "queued",
                func.cardinality(WikiUpdateJob.affected_document_ids)
                < WIKI_INCREMENTAL_DOCUMENT_BATCH_SIZE,
            )
            .order_by(WikiUpdateJob.created_at)
            .with_for_update()
        )
        should_send = queued is None
        if queued is None:
            knowledge_base = await session.get(KnowledgeBase, knowledge_base_id)
            if knowledge_base is None:
                return
            try:
                model = await resolve_wiki_model(session, knowledge_base)
            except WikiModelConfigurationError:
                return
            queued = WikiUpdateJob(
                space_id=space.id,
                model_id=model.id,
                status="queued",
                generation_id=uuid.uuid4(),
                affected_document_ids=[document_id],
            )
            session.add(queued)
        else:
            queued.affected_document_ids = list({*queued.affected_document_ids, document_id})
            if queued.model_id is None:
                knowledge_base = await session.get(KnowledgeBase, knowledge_base_id)
                if knowledge_base is None:
                    return
                try:
                    model = await resolve_wiki_model(session, knowledge_base)
                except WikiModelConfigurationError:
                    return
                queued.model_id = model.id
        await session.commit()
        if should_send:
            generate_wiki.send(str(queued.id))
