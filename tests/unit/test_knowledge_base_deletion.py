from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from synapsekb.api.routes import knowledge_bases as routes
from synapsekb.database.models import KnowledgeBase, TaskDispatch


def _admin() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role="admin")


def _knowledge_base() -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name="待删除知识库",
        description="",
        visibility="users",
        lifecycle_status="active",
        embedding_dimensions=1536,
        wiki_enabled=True,
        wiki_health_check_enabled=True,
        wiki_health_check_interval_hours=24,
        wiki_node_types=["主题"],
        wiki_generation_prompt="",
        created_by_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_delete_knowledge_base_requires_exact_name() -> None:
    knowledge_base = _knowledge_base()
    session = SimpleNamespace(scalar=AsyncMock(return_value=knowledge_base))

    with pytest.raises(HTTPException) as error:
        await routes.delete_knowledge_base_request(
            knowledge_base.id,
            routes.KnowledgeBaseDeletionRequest(confirmation_name="错误名称"),
            _admin(),
            session,
        )

    assert error.value.status_code == 422
    assert knowledge_base.lifecycle_status == "active"


@pytest.mark.asyncio
async def test_delete_knowledge_base_creates_async_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge_base = _knowledge_base()
    count_result = MagicMock()
    count_result.one.return_value = (2, 1)
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[knowledge_base, None]),
        execute=AsyncMock(return_value=count_result),
        add=MagicMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    send = AsyncMock()
    monkeypatch.setattr(routes, "publish_pending", send)

    job = await routes.delete_knowledge_base_request(
        knowledge_base.id,
        routes.KnowledgeBaseDeletionRequest(confirmation_name=knowledge_base.name),
        _admin(),
        session,
    )

    assert knowledge_base.lifecycle_status == "deleting"
    assert job.document_count == 2
    assert job.total_object_count == 3
    assert job.status == "queued"
    dispatch = next(
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], TaskDispatch)
    )
    assert dispatch.task_id == job.id
    send.assert_awaited_once_with(dispatch_id=dispatch.id)
    session.commit.assert_awaited_once()
