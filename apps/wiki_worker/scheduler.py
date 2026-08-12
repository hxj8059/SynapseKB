from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from synapsekb.config import get_settings
from synapsekb.database.models import (
    AgentRun,
    KnowledgeBase,
    ProcessingJob,
    WikiHealthJob,
    WikiSpace,
    WikiUpdateJob,
)
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.wiki.model_selection import (
    WikiModelConfigurationError,
    resolve_wiki_health_model,
)

from apps.agent_runner.actors import execute_agent_run
from apps.document_worker.actors import process_document
from apps.ocr_worker.actors import process_ocr
from apps.wiki_worker.actors import check_wiki_health, generate_wiki

logger = structlog.get_logger()
WIKI_UPDATE_STALE_AFTER = timedelta(minutes=30)
ORPHANED_QUEUE_AFTER = timedelta(minutes=2)


async def recover_orphaned_queued_tasks() -> dict[str, list[uuid.UUID]]:
    """Reconcile durable queued rows with potentially lost broker messages."""

    recovered: dict[str, list[uuid.UUID]] = {
        "document": [],
        "ocr": [],
        "agent": [],
        "wiki_update": [],
        "wiki_health": [],
    }
    async with AsyncSessionFactory() as session:
        stale_before = datetime.now(UTC) - ORPHANED_QUEUE_AFTER
        processing_jobs = list(
            (
                await session.scalars(
                    select(ProcessingJob)
                    .where(
                        ProcessingJob.status == "queued",
                        ProcessingJob.updated_at < stale_before,
                    )
                    .order_by(ProcessingJob.updated_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for processing_job in processing_jobs:
            category = "ocr" if processing_job.stage == "waiting_ocr" else "document"
            recovered[category].append(processing_job.id)
            processing_job.metadata_json = {
                **processing_job.metadata_json,
                "queue_recovery_count": int(
                    processing_job.metadata_json.get("queue_recovery_count", 0) or 0
                )
                + 1,
                "queue_recovered_at": datetime.now(UTC).isoformat(),
            }

        agent_runs = list(
            (
                await session.scalars(
                    select(AgentRun)
                    .where(
                        AgentRun.status == "queued",
                        AgentRun.updated_at < stale_before,
                    )
                    .order_by(AgentRun.updated_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for run in agent_runs:
            recovered["agent"].append(run.id)
            run.state_json = {
                **run.state_json,
                "queue_recovery_count": int(
                    run.state_json.get("queue_recovery_count", 0) or 0
                )
                + 1,
                "queue_recovered_at": datetime.now(UTC).isoformat(),
            }

        wiki_jobs = list(
            (
                await session.scalars(
                    select(WikiUpdateJob)
                    .where(
                        WikiUpdateJob.status == "queued",
                        WikiUpdateJob.updated_at < stale_before,
                    )
                    .order_by(WikiUpdateJob.updated_at)
                    .limit(20)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for wiki_job in wiki_jobs:
            recovered["wiki_update"].append(wiki_job.id)
            wiki_job.quality_report = {
                **wiki_job.quality_report,
                "queue_recovery_count": int(
                    wiki_job.quality_report.get("queue_recovery_count", 0) or 0
                )
                + 1,
                "queue_recovered_at": datetime.now(UTC).isoformat(),
            }

        health_jobs = list(
            (
                await session.scalars(
                    select(WikiHealthJob)
                    .where(
                        WikiHealthJob.status == "queued",
                        WikiHealthJob.updated_at < stale_before,
                    )
                    .order_by(WikiHealthJob.updated_at)
                    .limit(20)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for health_job in health_jobs:
            recovered["wiki_health"].append(health_job.id)
            health_job.report = {
                **health_job.report,
                "queue_recovery_count": int(
                    health_job.report.get("queue_recovery_count", 0) or 0
                )
                + 1,
                "queue_recovered_at": datetime.now(UTC).isoformat(),
            }
        await session.commit()

    for job_id in recovered["document"]:
        process_document.send(str(job_id))
    for job_id in recovered["ocr"]:
        process_ocr.send(str(job_id))
    for run_id in recovered["agent"]:
        execute_agent_run.send(str(run_id))
    for job_id in recovered["wiki_update"]:
        generate_wiki.send(str(job_id))
    for job_id in recovered["wiki_health"]:
        check_wiki_health.send(str(job_id))
    return recovered


async def recover_stale_wiki_updates() -> list[uuid.UUID]:
    """Requeue jobs whose worker disappeared after claiming them."""

    recovered_ids: list[uuid.UUID] = []
    async with AsyncSessionFactory() as session:
        stale_before = datetime.now(UTC) - WIKI_UPDATE_STALE_AFTER
        jobs = list(
            (
                await session.scalars(
                    select(WikiUpdateJob)
                    .where(
                        WikiUpdateJob.status == "running",
                        WikiUpdateJob.updated_at < stale_before,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for job in jobs:
            job.status = "queued"
            job.quality_report = {
                **job.quality_report,
                "recovery_count": int(job.quality_report.get("recovery_count", 0) or 0) + 1,
                "recovery_reason": "Worker 心跳超过 30 分钟未更新，任务已自动续跑",
                "recovered_at": datetime.now(UTC).isoformat(),
            }
            recovered_ids.append(job.id)
        await session.commit()
    for job_id in recovered_ids:
        generate_wiki.send(str(job_id))
    return recovered_ids


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
                        KnowledgeBase.wiki_enabled.is_(True),
                        KnowledgeBase.wiki_health_check_enabled.is_(True),
                    )
                )
            ).all()
        )
        now = datetime.now(UTC)
        for space in spaces:
            knowledge_base = await session.get(KnowledgeBase, space.knowledge_base_id)
            if knowledge_base is None:
                continue
            active = await session.scalar(
                select(WikiHealthJob.id).where(
                    WikiHealthJob.space_id == space.id,
                    WikiHealthJob.status.in_(["queued", "running"]),
                )
            )
            if active is not None:
                continue
            latest_at = await session.scalar(
                select(func.max(WikiHealthJob.created_at)).where(WikiHealthJob.space_id == space.id)
            )
            interval = timedelta(hours=knowledge_base.wiki_health_check_interval_hours)
            if latest_at is not None and latest_at + interval > now:
                continue
            try:
                model = await resolve_wiki_health_model(session, knowledge_base)
            except WikiModelConfigurationError as exc:
                logger.warning(
                    "wiki_health_schedule_skipped",
                    knowledge_base_id=str(knowledge_base.id),
                    reason=str(exc),
                )
                continue
            job = WikiHealthJob(
                space_id=space.id,
                model_id=model.id,
                status="queued",
                trigger="scheduled",
                auto_repair=True,
            )
            session.add(job)
            await session.flush()
            queued_ids.append(job.id)
        await session.commit()
    for job_id in queued_ids:
        check_wiki_health.send(str(job_id))
    return queued_ids


async def run_scheduler() -> None:
    settings = get_settings()
    logger.info(
        "wiki_health_scheduler_started",
        poll_seconds=settings.wiki_health_scheduler_poll_seconds,
    )
    while True:
        try:
            orphaned = await recover_orphaned_queued_tasks()
            orphaned_count = sum(len(ids) for ids in orphaned.values())
            if orphaned_count:
                logger.warning(
                    "orphaned_tasks_requeued",
                    count=orphaned_count,
                    categories={key: len(ids) for key, ids in orphaned.items() if ids},
                )
            recovered = await recover_stale_wiki_updates()
            if recovered:
                logger.warning("stale_wiki_updates_requeued", count=len(recovered))
            queued = await enqueue_due_health_checks()
            if queued:
                logger.info("wiki_health_checks_queued", count=len(queued))
        except Exception:
            logger.exception("wiki_health_scheduler_iteration_failed")
        await asyncio.sleep(settings.wiki_health_scheduler_poll_seconds)


def main() -> None:
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
