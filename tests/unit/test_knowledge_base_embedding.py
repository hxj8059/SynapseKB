from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from synapsekb.api.routes import knowledge_bases as routes


async def test_probe_accepts_selected_knowledge_base_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SimpleNamespace(
        embeddings=AsyncMock(return_value=[[0.0] * 1024]),
        close=AsyncMock(),
    )
    create = MagicMock(return_value=provider)
    monkeypatch.setattr(routes, "create_provider", create)

    await routes._probe_embedding_dimensions(SimpleNamespace(), 1024)

    create.assert_called_once_with(ANY, embedding_dimensions=1024)
    provider.close.assert_awaited_once()


async def test_probe_rejects_vendor_fixed_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SimpleNamespace(
        embeddings=AsyncMock(return_value=[[0.0] * 1024]),
        close=AsyncMock(),
    )
    monkeypatch.setattr(routes, "create_provider", lambda *_args, **_kwargs: provider)

    with pytest.raises(HTTPException) as error:
        await routes._probe_embedding_dimensions(SimpleNamespace(), 1536)

    assert error.value.status_code == 422
    assert "实际返回 1024 维" in str(error.value.detail)
