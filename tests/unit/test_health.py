from __future__ import annotations

from types import SimpleNamespace

import pytest
from synapsekb.api.routes.health import health


class _Session:
    def __init__(self) -> None:
        self.executed = False

    async def execute(self, _statement: object) -> None:
        self.executed = True


class _Redis:
    def __init__(self) -> None:
        self.pinged = False

    async def ping(self) -> bool:
        self.pinged = True
        return True


@pytest.mark.asyncio
async def test_health_checks_postgres_and_redis() -> None:
    session = _Session()
    redis = _Redis()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(redis=redis)))

    result = await health(request, session)  # type: ignore[arg-type]

    assert result == {"status": "ok"}
    assert session.executed is True
    assert redis.pinged is True
