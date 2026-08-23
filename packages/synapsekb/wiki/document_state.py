from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.database.models import (
    Document,
    WikiDocumentState,
    WikiUpdateJob,
)

WIKI_MANUAL_INCREMENTAL_BATCH_SIZE = 20
WIKI_FAILED_RETRY_BATCH_SIZE = 20


def job_expected_document_ids(job: WikiUpdateJob) -> list[uuid.UUID]:
    coverage = job.quality_report.get("document_coverage", {})
    raw_ids = coverage.get("expected_document_ids", []) if isinstance(coverage, dict) else []
    parsed: list[uuid.UUID] = []
    if isinstance(raw_ids, list):
        for value in raw_ids:
            try:
                parsed.append(uuid.UUID(str(value)))
            except (TypeError, ValueError):
                continue
    return list(dict.fromkeys(parsed or job.affected_document_ids))


async def incremental_documents(
    session: AsyncSession,
    *,
    space_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    limit: int = WIKI_MANUAL_INCREMENTAL_BATCH_SIZE,
) -> list[Document]:
    state_matches_document = and_(
        WikiDocumentState.space_id == space_id,
        WikiDocumentState.document_id == Document.id,
    )
    query = (
        select(Document)
        .outerjoin(WikiDocumentState, state_matches_document)
        .where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.status == "ready",
            or_(
                WikiDocumentState.id.is_(None),
                WikiDocumentState.status != "succeeded",
                WikiDocumentState.last_successful_document_updated_at.is_(None),
                WikiDocumentState.last_successful_document_updated_at < Document.updated_at,
            ),
        )
        .order_by(Document.updated_at, Document.id)
        .limit(limit)
    )
    return list((await session.scalars(query)).all())


async def retryable_documents(
    session: AsyncSession,
    *,
    job: WikiUpdateJob,
    knowledge_base_id: uuid.UUID,
) -> list[Document]:
    documents = list(
        (
            await session.scalars(
                select(Document)
                .join(WikiDocumentState, WikiDocumentState.document_id == Document.id)
                .where(
                    WikiDocumentState.space_id == job.space_id,
                    WikiDocumentState.last_job_id == job.id,
                    WikiDocumentState.status == "failed",
                    Document.knowledge_base_id == knowledge_base_id,
                    Document.status == "ready",
                )
                .order_by(Document.created_at, Document.id)
                .limit(WIKI_FAILED_RETRY_BATCH_SIZE)
            )
        ).all()
    )
    if documents:
        return documents

    expected_ids = job_expected_document_ids(job)
    if not expected_ids:
        return []
    return list(
        (
            await session.scalars(
                select(Document)
                .where(
                    Document.id.in_(expected_ids),
                    Document.knowledge_base_id == knowledge_base_id,
                    Document.status == "ready",
                )
                .order_by(Document.created_at, Document.id)
                .limit(WIKI_FAILED_RETRY_BATCH_SIZE)
            )
        ).all()
    )


async def mark_documents_pending(
    session: AsyncSession,
    *,
    space_id: uuid.UUID,
    documents: Sequence[Document],
) -> None:
    states = await _states_by_document(session, space_id, [item.id for item in documents])
    for document in documents:
        state = states.get(document.id)
        if state is None:
            state = WikiDocumentState(
                space_id=space_id,
                document_id=document.id,
                status="pending",
            )
            session.add(state)
            states[document.id] = state
        elif state.status != "running":
            state.status = "pending"
        state.error_summary = None


async def mark_job_documents_running(
    session: AsyncSession,
    *,
    job: WikiUpdateJob,
    documents: Sequence[Document],
) -> None:
    states = await _states_by_document(session, job.space_id, [item.id for item in documents])
    for document in documents:
        state = states.get(document.id)
        if state is None:
            state = WikiDocumentState(
                space_id=job.space_id,
                document_id=document.id,
                status="running",
            )
            session.add(state)
            states[document.id] = state
        state.status = "running"
        state.target_document_updated_at = document.updated_at
        state.last_job_id = job.id
        state.error_summary = None
        state.attempt_count = (state.attempt_count or 0) + 1


async def mark_job_documents_failed(
    session: AsyncSession,
    *,
    job: WikiUpdateJob,
    document_ids: Iterable[uuid.UUID],
    error_summary: str,
) -> None:
    ids = list(dict.fromkeys(document_ids))
    if not ids:
        return
    documents = list(
        (
            await session.scalars(
                select(Document).where(
                    Document.id.in_(ids),
                    Document.status == "ready",
                )
            )
        ).all()
    )
    states = await _states_by_document(session, job.space_id, ids)
    now = datetime.now(UTC)
    for document in documents:
        state = states.get(document.id)
        if state is None:
            state = WikiDocumentState(
                space_id=job.space_id,
                document_id=document.id,
                target_document_updated_at=document.updated_at,
                attempt_count=1,
            )
            session.add(state)
        state.status = "failed"
        state.last_job_id = job.id
        state.error_summary = error_summary[:1000]
        state.processed_at = now


async def mark_job_documents_pending(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> None:
    states = list(
        (
            await session.scalars(
                select(WikiDocumentState).where(WikiDocumentState.last_job_id == job_id)
            )
        ).all()
    )
    for state in states:
        state.status = "pending"
        state.error_summary = None


async def mark_job_documents_succeeded(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> None:
    states = list(
        (
            await session.scalars(
                select(WikiDocumentState).where(WikiDocumentState.last_job_id == job_id)
            )
        ).all()
    )
    if not states:
        return
    documents = {
        document.id: document
        for document in (
            await session.scalars(
                select(Document).where(Document.id.in_([state.document_id for state in states]))
            )
        ).all()
    }
    now = datetime.now(UTC)
    for state in states:
        document = documents.get(state.document_id)
        if document is None:
            continue
        target_revision = state.target_document_updated_at or document.updated_at
        state.last_successful_document_updated_at = target_revision
        state.processed_at = now
        state.error_summary = None
        state.status = "succeeded" if document.updated_at <= target_revision else "pending"


async def _states_by_document(
    session: AsyncSession,
    space_id: uuid.UUID,
    document_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, WikiDocumentState]:
    if not document_ids:
        return {}
    states = list(
        (
            await session.scalars(
                select(WikiDocumentState).where(
                    WikiDocumentState.space_id == space_id,
                    WikiDocumentState.document_id.in_(document_ids),
                )
            )
        ).all()
    )
    return {state.document_id: state for state in states}
