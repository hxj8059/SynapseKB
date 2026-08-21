from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from synapsekb.api.routes import agents as routes


class _HistoryResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> list[dict[str, object]]:
        return self.rows


async def test_list_agent_runs_returns_paginated_lightweight_history(
    monkeypatch,
) -> None:
    user_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    run_id = uuid.uuid4()
    now = datetime.now(UTC)
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=1),
        execute=AsyncMock(
            return_value=_HistoryResult(
                [
                    {
                        "id": run_id,
                        "agent_id": agent_id,
                        "status": "completed",
                        "query": "比较两个时期的产业变化",
                        "error_summary": None,
                        "started_at": now,
                        "finished_at": now,
                        "created_at": now,
                        "updated_at": now,
                    }
                ]
            )
        ),
    )
    access = AsyncMock()
    monkeypatch.setattr(routes, "_get_accessible_agent", access)

    result = await routes.list_agent_runs(
        agent_id,
        SimpleNamespace(id=user_id, role="user"),
        session,
        limit=12,
        offset=24,
    )

    access.assert_awaited_once()
    assert result.total == 1
    assert result.limit == 12
    assert result.offset == 24
    assert result.items[0].id == run_id
    assert result.items[0].query == "比较两个时期的产业变化"
    assert not hasattr(result.items[0], "result")
    assert not hasattr(result.items[0], "citations")
