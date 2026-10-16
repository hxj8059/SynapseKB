import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from synapsekb.agent.final_answer import AgentFinalAnswerError
from synapsekb.database.models import TaskDispatch
from synapsekb.tasks import dispatch


@pytest.mark.parametrize(
    ("error", "expected", "will_retry"),
    [
        (AgentFinalAnswerError("两次答案恢复已耗尽"), "failed", False),
        (ConnectionError("临时连接中断"), "pending", True),
    ],
)
async def test_dispatch_respects_exhausted_final_recovery(monkeypatch, error, expected, will_retry):
    job_id, dispatch_id = uuid.uuid4(), uuid.uuid4()
    row = SimpleNamespace(
        id=dispatch_id,
        task_id=job_id,
        task_type="agent",
        status="sent",
        redis_message_id="message",
        attempts=0,
    )
    job = SimpleNamespace(
        status="running", cancel_requested_at=None, error_summary=None, finished_at=None
    )

    class Session:
        commit = AsyncMock()

        async def get(self, model, identifier):
            return row if model is TaskDispatch else job

        async def scalar(self, statement):
            return row

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    @asynccontextmanager
    async def connection():
        yield SimpleNamespace(
            scalar=AsyncMock(return_value=True), commit=AsyncMock(), execute=AsyncMock()
        )

    monkeypatch.setattr(dispatch, "AsyncSessionFactory", Session)
    monkeypatch.setattr(dispatch, "engine", SimpleNamespace(connect=connection))
    monkeypatch.setattr(
        dispatch,
        "CurrentMessage",
        SimpleNamespace(
            get_current_message=lambda: SimpleNamespace(
                options={"dispatch_id": str(dispatch_id), "redis_message_id": "message"},
            )
        ),
    )
    report = AsyncMock()
    await dispatch.run_dispatched("agent", job_id, AsyncMock(side_effect=error), on_error=report)
    assert row.status == expected
    assert row.attempts == 1
    assert job.status == ("queued" if will_retry else "failed")
    assert report.await_args.args == (error, will_retry, 1)
