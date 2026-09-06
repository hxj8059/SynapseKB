"""Database outbox, broker reconciliation and single-owner task execution.

Queue age is never evidence of loss. Redis .msgs retains prefetched/unacked
messages, too. PostgreSQL session locks fence worker executions for the entire
call, independently of the business sessions that commit intermediate progress.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from dramatiq import Message
from dramatiq.middleware import CurrentMessage
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.database.models import (
    AgentRun,
    Document,
    KnowledgeBaseDeletionJob,
    ProcessingJob,
    TaskDispatch,
    WikiHealthJob,
    WikiUpdateJob,
)
from synapsekb.database.session import AsyncSessionFactory, engine
from synapsekb.tasks.broker import broker

logger = structlog.get_logger()
# phase -> queue, actor, business model, retry count
TASKS: dict[str, tuple[str, str, type[Any], int]] = {
    "document": ("document", "process_document", ProcessingJob, 3),
    "document_resume": ("document", "process_document", ProcessingJob, 3),
    "ocr": ("ocr", "process_ocr", ProcessingJob, 3),
    "wiki_update": ("wiki", "generate_wiki", WikiUpdateJob, 0),
    "wiki_health": ("wiki", "check_wiki_health", WikiHealthJob, 2),
    "agent": ("agent", "execute_agent_run", AgentRun, 2),
    "kb_delete": ("maintenance", "delete_knowledge_base", KnowledgeBaseDeletionJob, 5),
}
TERMINAL = {"succeeded", "completed", "published", "cancelled"}
HEARTBEAT_TIMEOUT = timedelta(minutes=10)


def add_dispatch(session: AsyncSession, task_type: str, job: Any) -> TaskDispatch:
    """Call before committing the newly-created business task. No broker I/O."""
    if job.id is None:
        job.id = uuid.uuid4()
    queue, actor, _, _ = TASKS[task_type]
    row = TaskDispatch(
        id=uuid.uuid4(),
        task_type=task_type,
        task_id=job.id,
        queue_name=queue,
        actor_name=actor,
        redis_message_id=str(uuid.uuid4()),
        status="pending",
        attempts=0,
        available_at=datetime.now(UTC),
    )
    session.add(row)
    return row


async def broker_has_message(row: TaskDispatch) -> bool:
    """A prefetched message is still present here until ack/nack."""

    def check() -> bool:
        pipe = broker.client.pipeline(transaction=False)
        for queue in (row.queue_name, f"{row.queue_name}.DQ"):
            pipe.hexists(f"{broker.namespace}:{queue}.msgs", row.redis_message_id)
        return any(pipe.execute())

    return await asyncio.to_thread(check)


async def publish_pending(limit: int = 100, *, dispatch_id: uuid.UUID | None = None) -> int:
    """Publish with row locks; a send/commit crash reuses the preallocated Redis id."""
    count = 0
    async with AsyncSessionFactory() as session:
        query = (
            select(TaskDispatch)
            .where(
                TaskDispatch.status == "pending",
                TaskDispatch.available_at <= datetime.now(UTC),
            )
            .order_by(TaskDispatch.available_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if dispatch_id:
            query = query.where(TaskDispatch.id == dispatch_id)
        rows = list((await session.scalars(query)).all())
        for row in rows:
            try:
                if not await broker_has_message(row):
                    message: Message[Any] = Message(
                        queue_name=row.queue_name,
                        actor_name=row.actor_name,
                        args=(str(row.task_id),),
                        kwargs={},
                        options={
                            "dispatch_id": str(row.id),
                            "dispatch_message_key": row.redis_message_id,
                            "max_retries": 0,
                        },
                    )
                    sent = await asyncio.to_thread(broker.enqueue, message)
                    row.redis_message_id = str(sent.options["redis_message_id"])
                row.status = "sent"
                row.sent_at = datetime.now(UTC)
                row.error_summary = None
                count += 1
            except Exception as exc:
                # Keep durable pending work even if the caller's broker is down.
                row.error_summary = f"投递失败：{type(exc).__name__}"[:1000]
                row.available_at = datetime.now(UTC) + timedelta(seconds=30)
                logger.warning(
                    "task_publish_deferred", dispatch_id=str(row.id), error=type(exc).__name__
                )
        await session.commit()
    return count


async def _business_done(session: AsyncSession, row: TaskDispatch) -> bool:
    job = await session.get(TASKS[row.task_type][2], row.task_id)
    if job is None or job.status in TERMINAL:
        return True
    if getattr(job, "cancel_requested_at", None):
        job.status = "cancelled"
        if hasattr(job, "finished_at"):
            job.finished_at = datetime.now(UTC)
        if isinstance(job, ProcessingJob):
            document = await session.get(Document, job.document_id)
            if document is not None:
                document.status = "cancelled"
        return True
    return False


async def _heartbeat(dispatch_id: uuid.UUID) -> None:
    while True:
        await asyncio.sleep(30)
        async with AsyncSessionFactory() as session:
            await session.execute(
                update(TaskDispatch)
                .where(
                    TaskDispatch.id == dispatch_id,
                    TaskDispatch.status == "claimed",
                )
                .values(heartbeat_at=datetime.now(UTC))
            )
            await session.commit()


def _lock_key(row: TaskDispatch) -> str:
    # Processing/OCR phases of one job must not execute concurrently.
    group = (
        "processing" if row.task_type in {"document", "document_resume", "ocr"} else row.task_type
    )
    return f"dispatch:{group}:{row.task_id}"


async def run_dispatched(
    task_type: str,
    job_id: uuid.UUID,
    work: Callable[[], Coroutine[Any, Any, Any]],
    *,
    on_error: Callable[[Exception, bool, int], Coroutine[Any, Any, None]] | None = None,
) -> Any:
    message = CurrentMessage.get_current_message()
    dispatch_id = message.options.get("dispatch_id") if message else None
    # Adopt pre-upgrade messages without requiring a queue purge.
    async with AsyncSessionFactory() as session:
        if dispatch_id:
            row = await session.get(TaskDispatch, uuid.UUID(str(dispatch_id)))
        else:
            legacy_job = await session.get(TASKS[task_type][2], job_id)
            # Historical duplicates must not restart a terminal failure. Explicit retries
            # create a fresh business task and outbox record.
            if legacy_job is None or legacy_job.status in TERMINAL | {"failed", "quality_failed"}:
                return None
            if task_type == "document":
                job = await session.get(ProcessingJob, job_id)
                if job and job.stage == "ocr_completed":
                    task_type = "document_resume"
                elif job and job.stage in {"waiting_ocr", "ocr"}:
                    return None
            queue, actor, _, _ = TASKS[task_type]
            await session.execute(
                insert(TaskDispatch)
                .values(
                    id=uuid.uuid4(),
                    task_type=task_type,
                    task_id=job_id,
                    queue_name=queue,
                    actor_name=actor,
                    status="sent",
                    attempts=0,
                    redis_message_id=str(message.options.get("redis_message_id", uuid.uuid4()))
                    if message
                    else str(uuid.uuid4()),
                    available_at=datetime.now(UTC),
                    sent_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(constraint="uq_task_dispatch_identity")
            )
            await session.commit()
            row = await session.scalar(
                select(TaskDispatch).where(
                    TaskDispatch.task_type == task_type,
                    TaskDispatch.task_id == job_id,
                )
            )
        if row is None or row.task_id != job_id or row.status in {"finished", "failed"}:
            return None
        if message and str(message.options.get("redis_message_id")) != row.redis_message_id:
            return None  # obsolete retry/recovered delivery
        row_id, lock_key = row.id, _lock_key(row)

    async with engine.connect() as lock_connection:
        locked = await lock_connection.scalar(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": lock_key}
        )
        await lock_connection.commit()
        if not locked:
            return None
        heartbeat: asyncio.Task[None] | None = None
        try:
            async with AsyncSessionFactory() as session:
                current = await session.scalar(
                    select(TaskDispatch).where(TaskDispatch.id == row_id).with_for_update()
                )
                if current is None or current.status in {"finished", "failed"}:
                    return None
                if (
                    message
                    and str(message.options.get("redis_message_id")) != current.redis_message_id
                ):
                    return None
                if await _business_done(session, current):
                    current.status = "finished"
                    current.finished_at = datetime.now(UTC)
                    await session.commit()
                    return None
                current.status = "claimed"
                current.claimed_at = current.heartbeat_at = datetime.now(UTC)
                current.attempts += 1
                await session.commit()
            heartbeat = asyncio.create_task(_heartbeat(row_id))
            work_task = asyncio.create_task(work())
            try:
                # Losing the heartbeat also aborts local work; do not run an unfenced zombie.
                done, _ = await asyncio.wait(
                    {heartbeat, work_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if heartbeat in done:
                    await heartbeat
                result = await work_task
            finally:
                if not work_task.done():
                    work_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await work_task
            async with AsyncSessionFactory() as session:
                current = await session.get(TaskDispatch, row_id)
                if current is not None:
                    if result == "waiting" and task_type == "kb_delete":
                        current.status = "pending"
                        current.redis_message_id = str(uuid.uuid4())
                        current.available_at = datetime.now(UTC) + timedelta(seconds=15)
                        current.attempts -= 1
                    else:
                        current.status = "finished"
                        current.finished_at = datetime.now(UTC)
                    await session.commit()
            return result
        except Exception as exc:
            retry, attempt = False, 0
            async with AsyncSessionFactory() as session:
                current = await session.get(TaskDispatch, row_id)
                if current is not None:
                    attempt = current.attempts
                    current.error_summary = f"执行失败：{type(exc).__name__}"[:1000]
                    retry = current.attempts <= TASKS[current.task_type][
                        3
                    ] and not await _business_done(session, current)
                    current.status = "pending" if retry else "failed"
                    if retry:
                        current.redis_message_id = str(uuid.uuid4())
                        current.available_at = datetime.now(UTC) + timedelta(
                            seconds=min(120, 10 * 2**current.attempts)
                        )
                    else:
                        current.finished_at = datetime.now(UTC)
                    job = await session.get(TASKS[current.task_type][2], current.task_id)
                    if job is not None and job.status not in TERMINAL | {"quality_failed"}:
                        job.status = "queued" if retry else "failed"
                        if not job.error_summary:
                            job.error_summary = current.error_summary
                        if hasattr(job, "finished_at"):
                            job.finished_at = None if retry else datetime.now(UTC)
                        if isinstance(job, ProcessingJob):
                            document = await session.get(Document, job.document_id)
                            if document is not None:
                                document.status = "queued" if retry else "failed"
                    await session.commit()
            if on_error is not None:
                try:
                    await on_error(exc, retry, attempt)
                except Exception as notification_error:
                    logger.warning(
                        "task_failure_notification_failed",
                        dispatch_id=str(row_id),
                        error=type(notification_error).__name__,
                    )
            logger.warning(
                "task_execution_failed", dispatch_id=str(row_id), error=type(exc).__name__
            )
            return None  # Retry is durable in SQL; do not also trigger a broker retry.
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await heartbeat
            await lock_connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": lock_key}
            )


async def reconcile_dispatches(limit: int = 200) -> dict[str, int]:
    counts = {"missing": 0, "stale": 0, "finished": 0}
    async with AsyncSessionFactory() as session:
        rows = list(
            (
                await session.scalars(
                    select(TaskDispatch)
                    .where(
                        TaskDispatch.status.in_({"sent", "claimed"}),
                    )
                    .order_by(TaskDispatch.updated_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for row in rows:
            # Round-robin over long queues; never repeatedly inspect only the oldest page.
            row.updated_at = datetime.now(UTC)
            if row.status == "sent":
                if await broker_has_message(row):
                    continue
                if await _business_done(session, row):
                    row.status = "finished"
                    row.finished_at = datetime.now(UTC)
                    counts["finished"] += 1
                else:
                    row.status = "pending"
                    row.redis_message_id = str(uuid.uuid4())
                    row.available_at = datetime.now(UTC)
                    counts["missing"] += 1
            elif row.heartbeat_at and row.heartbeat_at < datetime.now(UTC) - HEARTBEAT_TIMEOUT:
                # A live lock is authoritative even when a slow network delayed its heartbeat.
                async with engine.connect() as connection:
                    key = _lock_key(row)
                    locked = await connection.scalar(
                        text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": key}
                    )
                    if not locked:
                        continue
                    try:
                        if await _business_done(session, row):
                            row.status = "finished"
                            row.finished_at = datetime.now(UTC)
                            counts["finished"] += 1
                        else:
                            row.status = "pending"
                            row.redis_message_id = str(uuid.uuid4())
                            row.available_at = datetime.now(UTC)
                            counts["stale"] += 1
                    finally:
                        await connection.execute(
                            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key}
                        )
        await session.commit()
    return counts
