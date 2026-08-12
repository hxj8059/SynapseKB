from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers
from synapsekb.api.routes import documents as document_routes
from synapsekb.database.models import Document, ProcessingJob, User

from apps.document_worker import actors as document_actors


class _UploadSession:
    """Small session fake that guards the ordering that caused MissingGreenlet."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flush_count = 0
        self.refresh_count = 0

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def scalar(self, statement: Any) -> None:
        del statement
        return None

    async def flush(self) -> None:
        self.flush_count += 1
        if self.flush_count > 1:
            raise AssertionError("initial upload must build its job before a second flush")
        document = next(item for item in self.added if isinstance(item, Document))
        now = datetime.now(UTC)
        document.id = uuid.uuid4()
        document.created_at = now
        document.updated_at = now

    async def commit(self) -> None:
        now = datetime.now(UTC)
        for item in self.added:
            if isinstance(item, ProcessingJob) and item.id is None:
                item.id = uuid.uuid4()
                item.created_at = now
                item.updated_at = now

    async def refresh(self, instance: Any) -> None:
        assert isinstance(instance, Document)
        self.refresh_count += 1


class _UploadStorage:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def put_file(self, key: str, path: Path, content_type: str) -> None:
        assert path.read_bytes() == b"SynapseKB upload regression test"
        assert content_type == "text/plain"
        self.keys.append(key)


@pytest.mark.asyncio
async def test_upload_builds_job_before_timestamp_can_expire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _UploadSession()
    storage = _UploadStorage()
    sent_job_ids: list[str] = []

    async def allow_access(*args: object, **kwargs: object) -> None:
        del args, kwargs

    async def create_storage(session_arg: object) -> _UploadStorage:
        assert session_arg is session
        return storage

    monkeypatch.setattr(document_routes, "require_knowledge_base_access", allow_access)
    monkeypatch.setattr(document_routes, "create_runtime_storage", create_storage)
    monkeypatch.setattr(
        document_actors.process_document,
        "send",
        lambda job_id: sent_job_ids.append(job_id),
    )

    user = User(
        id=uuid.uuid4(),
        email="admin@synapsekb.cn",
        display_name="管理员",
        password_hash="unused",  # noqa: S106 - authentication is outside this route test
        role="admin",
        is_active=True,
        timezone="Asia/Shanghai",
    )
    upload = UploadFile(
        BytesIO(b"SynapseKB upload regression test"),
        filename="regression.txt",
        headers=Headers({"content-type": "text/plain"}),
    )

    result = await document_routes.upload_document(
        user=user,
        session=session,  # type: ignore[arg-type]
        knowledge_base_id=uuid.uuid4(),
        file=upload,
        title=None,
        source_time=None,
    )

    jobs = [item for item in session.added if isinstance(item, ProcessingJob)]
    assert session.flush_count == 1
    assert session.refresh_count == 1
    assert result.status == "queued"
    assert len(storage.keys) == 1
    assert len(jobs) == 1
    assert sent_job_ids == [str(jobs[0].id)]
