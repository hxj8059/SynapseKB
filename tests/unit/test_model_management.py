from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from httpx import Request, Response
from openai import BadRequestError
from synapsekb.api.routes import models as model_routes


def _admin() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role="admin")


def _model() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Rerank",
        kind="rerank",
        provider="dashscope",
    )


@pytest.mark.asyncio
async def test_delete_model_rejects_configured_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model()
    session = SimpleNamespace(get=AsyncMock(return_value=model))
    monkeypatch.setattr(
        model_routes,
        "_configured_references",
        AsyncMock(return_value=["知识库：产业链"]),
    )

    with pytest.raises(HTTPException) as error:
        await model_routes.delete_model(model.id, _admin(), session)

    assert error.value.status_code == 409
    assert "知识库：产业链" in str(error.value.detail)


@pytest.mark.asyncio
async def test_delete_unreferenced_model_writes_audit_and_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model()
    session = SimpleNamespace(
        get=AsyncMock(return_value=model),
        add=MagicMock(),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(
        model_routes,
        "_configured_references",
        AsyncMock(return_value=[]),
    )

    await model_routes.delete_model(model.id, _admin(), session)

    session.delete.assert_awaited_once_with(model)
    session.commit.assert_awaited_once()
    assert session.add.call_count == 1


def test_provider_error_details_are_actionable_and_do_not_expose_headers() -> None:
    request = Request(
        "POST",
        "https://tokenhub.tencentmaas.com/v1/embeddings",
        headers={"Authorization": "Bearer secret"},
    )
    response = Response(
        400,
        request=request,
        json={
            "error": {
                "code": "400001",
                "message": "dimensions is not supported",
                "message_zh": "不支持 dimensions 参数",
                "request_id": "vendor-request-id",
            }
        },
    )
    error = BadRequestError(
        "bad request",
        response=response,
        body=response.json(),
    )

    details = model_routes._model_error_details(error)

    assert details["http_status"] == 400
    assert details["provider_code"] == "400001"
    assert details["message_zh"] == "不支持 dimensions 参数"
    assert details["endpoint"] == "https://tokenhub.tencentmaas.com/v1/embeddings"
    assert "secret" not in str(details)
