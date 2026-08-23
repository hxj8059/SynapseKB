import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession
from synapsekb.api.schemas import WikiGenerateRequest
from synapsekb.database.models import Document, WikiDocumentState, WikiUpdateJob
from synapsekb.wiki.document_state import (
    job_expected_document_ids,
    mark_job_documents_succeeded,
)


def test_manual_wiki_generation_defaults_to_incremental() -> None:
    payload = WikiGenerateRequest(knowledge_base_id=uuid.uuid4())

    assert payload.mode == "incremental"
    assert payload.document_ids == []


def test_retry_uses_coverage_ids_before_affected_ids() -> None:
    coverage_ids = [uuid.uuid4(), uuid.uuid4()]
    job = WikiUpdateJob(
        affected_document_ids=[uuid.uuid4()],
        quality_report={
            "document_coverage": {
                "expected_document_ids": [str(item) for item in coverage_ids],
            }
        },
    )

    assert job_expected_document_ids(job) == coverage_ids


async def test_success_state_stays_pending_if_document_changed_during_job() -> None:
    job_id = uuid.uuid4()
    document_id = uuid.uuid4()
    target_revision = datetime(2026, 8, 23, 10, tzinfo=UTC)
    document = Document(
        id=document_id,
        knowledge_base_id=uuid.uuid4(),
        filename="report.md",
        title="report",
        media_type="text/markdown",
        size_bytes=10,
        sha256="a" * 64,
        object_key="documents/report.md",
        status="ready",
        created_by_id=uuid.uuid4(),
        updated_at=target_revision + timedelta(minutes=1),
    )
    state = WikiDocumentState(
        space_id=uuid.uuid4(),
        document_id=document_id,
        status="running",
        target_document_updated_at=target_revision,
        last_job_id=job_id,
        attempt_count=1,
    )
    scalar_results = [
        SimpleNamespace(all=lambda: [state]),
        SimpleNamespace(all=lambda: [document]),
    ]
    session = cast(
        AsyncSession,
        SimpleNamespace(scalars=AsyncMock(side_effect=scalar_results)),
    )

    await mark_job_documents_succeeded(session, job_id=job_id)

    assert state.last_successful_document_updated_at == target_revision
    assert state.status == "pending"
    assert state.error_summary is None
