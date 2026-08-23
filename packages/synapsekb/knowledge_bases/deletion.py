from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.database.models import (
    AuditLog,
    Document,
    KnowledgeBase,
    KnowledgeBaseDeletionJob,
    ProcessingJob,
    WikiHealthJob,
    WikiSpace,
    WikiUpdateJob,
)
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.storage.factory import create_runtime_storage

logger = structlog.get_logger()

OBJECT_BATCH_DOCUMENTS = 500
STALE_TASK_AFTER = timedelta(hours=2)
TERMINAL_PROCESSING_STATUSES = {"succeeded", "failed", "cancelled"}
TERMINAL_WIKI_UPDATE_STATUSES = {"published", "failed", "quality_failed", "cancelled"}
TERMINAL_WIKI_HEALTH_STATUSES = {"completed", "failed", "cancelled"}


async def _request_task_cancellation(
    session: AsyncSession,
    knowledge_base_id: uuid.UUID,
) -> int:
    # The concrete type is deliberately inferred by SQLAlchemy at runtime; this
    # helper stays small enough to be reused by the API and maintenance worker.
    now = datetime.now(UTC)
    stale_before = now - STALE_TASK_AFTER
    document_ids = select(Document.id).where(Document.knowledge_base_id == knowledge_base_id)
    await session.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.document_id.in_(document_ids),
            ProcessingJob.status.not_in(TERMINAL_PROCESSING_STATUSES),
        )
        .values(
            cancel_requested_at=now,
            status=case(
                (
                    (ProcessingJob.status == "queued")
                    | (ProcessingJob.updated_at < stale_before),
                    "cancelled",
                ),
                else_=ProcessingJob.status,
            ),
            finished_at=case(
                (
                    (ProcessingJob.status == "queued")
                    | (ProcessingJob.updated_at < stale_before),
                    now,
                ),
                else_=ProcessingJob.finished_at,
            ),
        )
    )
    space_ids = select(WikiSpace.id).where(WikiSpace.knowledge_base_id == knowledge_base_id)
    await session.execute(
        update(WikiUpdateJob)
        .where(
            WikiUpdateJob.space_id.in_(space_ids),
            WikiUpdateJob.status.not_in(TERMINAL_WIKI_UPDATE_STATUSES),
        )
        .values(
            cancel_requested_at=now,
            status=case(
                (
                    (WikiUpdateJob.status == "queued")
                    | (WikiUpdateJob.updated_at < stale_before),
                    "cancelled",
                ),
                else_=WikiUpdateJob.status,
            ),
        )
    )
    await session.execute(
        update(WikiHealthJob)
        .where(
            WikiHealthJob.space_id.in_(space_ids),
            WikiHealthJob.status.not_in(TERMINAL_WIKI_HEALTH_STATUSES),
        )
        .values(
            cancel_requested_at=now,
            status=case(
                (
                    (WikiHealthJob.status == "queued")
                    | (WikiHealthJob.updated_at < stale_before),
                    "cancelled",
                ),
                else_=WikiHealthJob.status,
            ),
            finished_at=case(
                (
                    (WikiHealthJob.status == "queued")
                    | (WikiHealthJob.updated_at < stale_before),
                    now,
                ),
                else_=WikiHealthJob.finished_at,
            ),
        )
    )
    active_processing = int(
        await session.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.document_id.in_(document_ids),
                ProcessingJob.status == "running",
            )
        )
        or 0
    )
    active_wiki_updates = int(
        await session.scalar(
            select(func.count())
            .select_from(WikiUpdateJob)
            .where(
                WikiUpdateJob.space_id.in_(space_ids),
                WikiUpdateJob.status.in_({"running", "quality_check"}),
            )
        )
        or 0
    )
    active_wiki_health = int(
        await session.scalar(
            select(func.count())
            .select_from(WikiHealthJob)
            .where(
                WikiHealthJob.space_id.in_(space_ids),
                WikiHealthJob.status == "running",
            )
        )
        or 0
    )
    return active_processing + active_wiki_updates + active_wiki_health


async def run_knowledge_base_deletion(job_id: uuid.UUID) -> str:
    """Delete storage objects in resumable batches, then atomically remove DB data."""

    async with AsyncSessionFactory() as session:
        job = await session.get(KnowledgeBaseDeletionJob, job_id)
        if job is None or job.status == "completed":
            return "completed"
        knowledge_base = (
            await session.get(KnowledgeBase, job.knowledge_base_id)
            if job.knowledge_base_id is not None
            else None
        )
        if knowledge_base is None:
            job.status = "completed"
            job.stage = "completed"
            job.progress = 1
            job.finished_at = datetime.now(UTC)
            await session.commit()
            return "completed"

        job.status = "running"
        job.stage = "cancelling_tasks"
        job.started_at = job.started_at or datetime.now(UTC)
        job.error_summary = None
        active_task_count = await _request_task_cancellation(session, knowledge_base.id)
        if active_task_count:
            job.status = "waiting_tasks"
            job.stage = "waiting_for_running_tasks"
            job.progress = max(job.progress, 0.02)
            job.metadata_json = {
                **job.metadata_json,
                "active_task_count": active_task_count,
            }
            await session.commit()
            return "waiting"
        await session.commit()

        storage = await create_runtime_storage(session)
        cursor_value = job.metadata_json.get("last_document_id")
        cursor = uuid.UUID(str(cursor_value)) if cursor_value else None
        while True:
            query = (
                select(Document.id, Document.object_key, Document.parsed_text_key)
                .where(Document.knowledge_base_id == knowledge_base.id)
                .order_by(Document.id)
                .limit(OBJECT_BATCH_DOCUMENTS)
            )
            if cursor is not None:
                query = query.where(Document.id > cursor)
            rows = list((await session.execute(query)).all())
            if not rows:
                break
            keys = list(
                dict.fromkeys(
                    key
                    for row in rows
                    for key in (row.object_key, row.parsed_text_key)
                    if key
                )
            )
            await storage.delete_many(keys)
            cursor = rows[-1].id
            job.deleted_object_count += len(keys)
            job.stage = "deleting_objects"
            job.progress = min(
                0.94,
                0.05
                + 0.89
                * job.deleted_object_count
                / max(job.total_object_count, 1),
            )
            job.metadata_json = {
                **job.metadata_json,
                "last_document_id": str(cursor),
                "active_task_count": 0,
            }
            await session.commit()

        job.stage = "deleting_database"
        job.progress = 0.97
        session.add(
            AuditLog(
                actor_user_id=job.requested_by_id,
                action="knowledge_base.delete",
                resource_type="knowledge_base",
                resource_id=knowledge_base.id,
                metadata_json={
                    "name": knowledge_base.name,
                    "document_count": job.document_count,
                    "deleted_object_count": job.deleted_object_count,
                    "deletion_job_id": str(job.id),
                },
                created_at=datetime.now(UTC),
            )
        )
        await session.delete(knowledge_base)
        job.status = "completed"
        job.stage = "completed"
        job.progress = 1
        job.finished_at = datetime.now(UTC)
        await session.commit()
        logger.info(
            "knowledge_base_deleted",
            knowledge_base_id=str(job.knowledge_base_snapshot_id),
            deletion_job_id=str(job.id),
            document_count=job.document_count,
            object_count=job.deleted_object_count,
        )
        return "completed"


async def mark_knowledge_base_deletion_failed(job_id: uuid.UUID, exc: Exception) -> None:
    async with AsyncSessionFactory() as session:
        job = await session.get(KnowledgeBaseDeletionJob, job_id)
        if job is None or job.status == "completed":
            return
        summary = f"{type(exc).__name__}: {exc}"[:1000]
        job.status = "failed"
        job.stage = "failed"
        job.error_summary = summary
        job.finished_at = datetime.now(UTC)
        if job.knowledge_base_id is not None:
            knowledge_base = await session.get(KnowledgeBase, job.knowledge_base_id)
            if knowledge_base is not None:
                knowledge_base.lifecycle_status = "deletion_failed"
        await session.commit()
        logger.exception(
            "knowledge_base_deletion_failed",
            deletion_job_id=str(job_id),
            error_summary=summary,
        )
