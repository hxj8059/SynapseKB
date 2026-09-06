from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from synapsekb.config import get_settings
from synapsekb.database.models import KnowledgeBase, WikiHealthJob, WikiSpace
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.tasks.dispatch import add_dispatch, publish_pending, reconcile_dispatches
from synapsekb.wiki.model_selection import WikiModelConfigurationError, resolve_wiki_health_model

logger = structlog.get_logger()


async def enqueue_due_health_checks() -> list[uuid.UUID]:
    queued_ids: list[uuid.UUID] = []
    async with AsyncSessionFactory() as session:
        spaces = list(
            (
                await session.scalars(
                    select(WikiSpace)
                    .join(KnowledgeBase, KnowledgeBase.id == WikiSpace.knowledge_base_id)
                    .where(
                        WikiSpace.published_version.is_not(None),
                        KnowledgeBase.lifecycle_status == "active",
                        KnowledgeBase.wiki_enabled.is_(True),
                        KnowledgeBase.wiki_health_check_enabled.is_(True),
                    )
                    .with_for_update(of=WikiSpace, skip_locked=True)
                )
            ).all()
        )
        now = datetime.now(UTC)
        for space in spaces:
            kb = await session.get(KnowledgeBase, space.knowledge_base_id)
            if kb is None:
                continue
            active = await session.scalar(
                select(WikiHealthJob.id).where(
                    WikiHealthJob.space_id == space.id,
                    WikiHealthJob.status.in_(["queued", "running"]),
                )
            )
            if active:
                continue
            latest = await session.scalar(
                select(func.max(WikiHealthJob.created_at)).where(
                    WikiHealthJob.space_id == space.id,
                )
            )
            if latest and latest + timedelta(hours=kb.wiki_health_check_interval_hours) > now:
                continue
            try:
                model = await resolve_wiki_health_model(session, kb)
            except WikiModelConfigurationError:
                continue
            job = WikiHealthJob(
                space_id=space.id,
                model_id=model.id,
                status="queued",
                trigger="scheduled",
                auto_repair=True,
            )
            session.add(job)
            add_dispatch(session, "wiki_health", job)
            queued_ids.append(job.id)
        await session.commit()
    return queued_ids


async def run_scheduler() -> None:
    settings = get_settings()
    next_health_check = datetime.now(UTC)
    logger.info("task_dispatch_scheduler_started", dispatch_poll_seconds=10)
    while True:
        try:
            counts = await reconcile_dispatches()
            if any(counts.values()):
                logger.info("task_dispatch_reconciled", **counts)
            if datetime.now(UTC) >= next_health_check:
                await enqueue_due_health_checks()
                next_health_check = datetime.now(UTC) + timedelta(
                    seconds=settings.wiki_health_scheduler_poll_seconds
                )
            await publish_pending()
        except Exception:
            logger.exception("task_dispatch_scheduler_iteration_failed")
        await asyncio.sleep(10)


def main() -> None:
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
