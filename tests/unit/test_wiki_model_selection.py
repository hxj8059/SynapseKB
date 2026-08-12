import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from synapsekb.database.models import KnowledgeBase, ProviderModel
from synapsekb.wiki.model_selection import (
    WikiModelConfigurationError,
    resolve_wiki_health_model,
    resolve_wiki_model,
)


def _chat_model(name: str) -> ProviderModel:
    return ProviderModel(
        id=uuid.uuid4(),
        name=name,
        kind="chat",
        provider="openai-compatible",
        base_url="https://model.example/v1",
        model_name=name,
        encrypted_api_key=None,
        timeout_seconds=60,
        max_concurrency=2,
        embedding_dimensions=None,
        is_enabled=True,
        config={},
    )


async def test_explicit_wiki_model_is_used() -> None:
    model = _chat_model("wiki-chat")
    session = cast(AsyncSession, SimpleNamespace(get=AsyncMock(return_value=model)))
    knowledge_base = KnowledgeBase(wiki_chat_model_id=model.id)

    selected = await resolve_wiki_model(session, knowledge_base)

    assert selected.id == model.id


async def test_multiple_chat_models_require_explicit_wiki_selection() -> None:
    models = [_chat_model("chat-a"), _chat_model("chat-b")]
    scalar_result = SimpleNamespace(all=lambda: models)
    session = cast(
        AsyncSession,
        SimpleNamespace(scalars=AsyncMock(return_value=scalar_result)),
    )
    knowledge_base = KnowledgeBase(wiki_chat_model_id=None)

    with pytest.raises(WikiModelConfigurationError, match="明确选择"):
        await resolve_wiki_model(session, knowledge_base)


async def test_wiki_health_uses_separate_model() -> None:
    generation_model = _chat_model("wiki-generation")
    health_model = _chat_model("wiki-health")
    session = cast(
        AsyncSession,
        SimpleNamespace(get=AsyncMock(return_value=health_model)),
    )
    knowledge_base = KnowledgeBase(
        wiki_chat_model_id=generation_model.id,
        wiki_health_chat_model_id=health_model.id,
    )

    selected = await resolve_wiki_health_model(session, knowledge_base)

    assert selected.id == health_model.id
