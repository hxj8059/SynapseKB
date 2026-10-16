from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from synapsekb.database.models import ProviderModel
from synapsekb.models.provider import (
    DeterministicMockProvider,
    OpenAICompatibleProvider,
    create_provider,
    effective_chat_extra_body,
    normalize_model_base_url,
    validate_model_transport,
)


class FakeChatCompletions:
    def __init__(
        self,
        content: str,
        *,
        finish_reason: str = "stop",
        reasoning_content: str = "",
        reasoning_tokens: int | None = None,
    ) -> None:
        self.content = content
        self.finish_reason = finish_reason
        self.reasoning_content = reasoning_content
        self.reasoning_tokens = reasoning_tokens
        self.params: dict[str, Any] = {}

    async def create(self, **params: Any) -> Any:
        self.params = params
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=self.content,
                        reasoning_content=self.reasoning_content,
                    ),
                    finish_reason=self.finish_reason,
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=20,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=self.reasoning_tokens),
            ),
        )


@asynccontextmanager
async def no_model_quota() -> AsyncIterator[None]:
    yield


async def test_mock_embeddings_are_repeatable_and_dimensioned() -> None:
    provider = DeterministicMockProvider(dimensions=8)
    first = await provider.embeddings(["触智"])
    second = await provider.embeddings(["触智"])
    assert first == second
    assert len(first[0]) == 8
    assert all(-1 <= value <= 1 for value in first[0])


async def test_stream_closes_and_applies_request_scoped_timeouts_and_reasoning_control() -> None:
    provider = OpenAICompatibleProvider(
        api_key="test",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen-test",
    )
    events = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, reasoning_content="隐藏推理"),
                    finish_reason=None,
                )
            ],
            usage=None,
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="正文", reasoning_content=None),
                    finish_reason="stop",
                )
            ],
            usage=None,
        ),
        SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2)),
    ]

    class Stream:
        close = AsyncMock()

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not events:
                raise StopAsyncIteration
            return events.pop(0)

    stream = Stream()
    completions = SimpleNamespace(create=AsyncMock(return_value=stream))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    # with_options is synchronous in the SDK; capture its per-request overrides.
    client.with_options = Mock(return_value=client)
    provider.client = client
    provider.quota = no_model_quota
    result = [
        part
        async for part in provider.chat_stream(
            [{"role": "user", "content": "回答"}],
            max_tokens=4000,
            disable_reasoning=True,
            timeout_seconds=30,
            max_retries=0,
        )
    ]
    assert result == ["正文"]
    assert provider.last_chat_finish_reason == "stop"
    assert provider.last_chat_usage == {"prompt_tokens": 10, "completion_tokens": 2}
    client.with_options.assert_called_once_with(timeout=30, max_retries=0)
    assert completions.create.call_args.kwargs["extra_body"] == {"enable_thinking": False}
    assert provider.chat_extra_body == {}
    stream.close.assert_awaited_once()
    await provider.http.aclose()


async def test_dashscope_rerank_uses_plural_compatible_endpoint() -> None:
    model = ProviderModel(
        name="dashscope-rerank",
        kind="rerank",
        provider="dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3-rerank",
        encrypted_api_key=None,
        timeout_seconds=60,
        max_concurrency=5,
        embedding_dimensions=None,
        config={},
    )
    provider = create_provider(model)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.rerank_path == "/reranks"
    await provider.close()


def test_full_operation_endpoint_is_normalized_to_api_root() -> None:
    assert (
        normalize_model_base_url(
            "embedding",
            "https://tokenhub.tencentmaas.com/v1/embeddings",
        )
        == "https://tokenhub.tencentmaas.com/v1"
    )
    assert (
        normalize_model_base_url(
            "chat",
            "https://model.example/v1/chat/completions",
        )
        == "https://model.example/v1"
    )


async def test_tencent_embedding_uses_vendor_compatible_parameters() -> None:
    model = ProviderModel(
        name="tencent-embedding",
        kind="embedding",
        provider="openai-compatible",
        base_url="https://tokenhub.tencentmaas.com/v1/embeddings",
        model_name="kinfra-text-embedding-0.6b",
        encrypted_api_key=None,
        timeout_seconds=60,
        max_concurrency=5,
        embedding_dimensions=1024,
        config={},
    )
    provider = create_provider(model)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert str(provider.client.base_url) == "https://tokenhub.tencentmaas.com/v1/"
    assert provider.embedding_send_dimensions is False
    assert provider.embedding_encoding_format == "float"
    await provider.close()


async def test_dashscope_embedding_uses_knowledge_base_dimension() -> None:
    model = ProviderModel(
        name="dashscope-embedding",
        kind="embedding",
        provider="dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="text-embedding-v4",
        encrypted_api_key=None,
        timeout_seconds=60,
        max_concurrency=5,
        embedding_dimensions=1536,
        config={},
    )
    provider = create_provider(model, embedding_dimensions=1024)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.embedding_dimensions == 1024
    assert provider.embedding_send_dimensions is None
    assert provider.embedding_encoding_format == "float"
    await provider.close()


async def test_chat_json_requests_complete_json_response() -> None:
    provider = OpenAICompatibleProvider(
        api_key="test",
        base_url="https://model.example/v1",
        model_name="reasoning-model",
        chat_extra_body={"enable_thinking": False},
    )
    completions = FakeChatCompletions('{"ok":true}')
    provider.client = cast(
        Any,
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    provider.quota = no_model_quota  # type: ignore[method-assign]

    result = await provider.chat_json(
        [{"role": "user", "content": "输出 JSON"}],
        max_tokens=12000,
    )

    assert result == '{"ok":true}'
    assert completions.params["response_format"] == {"type": "json_object"}
    assert completions.params["max_tokens"] == 12000
    assert completions.params["extra_body"] == {"enable_thinking": False}
    await provider.http.aclose()


async def test_tencent_structured_call_can_disable_reasoning_per_request() -> None:
    provider = OpenAICompatibleProvider(
        api_key="test",
        base_url="https://tokenhub.tencentmaas.com/v1",
        model_name="reasoning-model",
    )
    completions = FakeChatCompletions('{"ok":true}')
    provider.client = cast(
        Any,
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    provider.quota = no_model_quota  # type: ignore[method-assign]

    await provider.chat_json(
        [{"role": "user", "content": "输出 JSON"}],
        max_tokens=10_000,
        disable_reasoning=True,
    )

    assert completions.params["extra_body"] == {"thinking": {"type": "disabled"}}
    await provider.http.aclose()


async def test_chat_json_rejects_length_even_when_partial_content_exists() -> None:
    provider = OpenAICompatibleProvider(
        api_key="test",
        base_url="https://model.example/v1",
        model_name="reasoning-model",
        chat_extra_body={"enable_thinking": False},
    )
    completions = FakeChatCompletions(
        '{"nodes":[',
        finish_reason="length",
        reasoning_content="hidden",
        reasoning_tokens=18,
    )
    provider.client = cast(
        Any,
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    provider.quota = no_model_quota  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="reasoning_tokens=18"):
        await provider.chat_json(
            [{"role": "user", "content": "输出 JSON"}],
            max_tokens=20,
        )
    await provider.http.aclose()


async def test_chat_probe_reports_ignored_reasoning_disable_parameter() -> None:
    provider = OpenAICompatibleProvider(
        api_key="test",
        base_url="https://model.example/v1",
        model_name="reasoning-model",
        chat_extra_body={"enable_thinking": False},
    )
    completions = FakeChatCompletions(
        '{"ok":true}',
        reasoning_content="hidden",
        reasoning_tokens=12,
    )
    provider.client = cast(
        Any,
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    provider.quota = no_model_quota  # type: ignore[method-assign]

    result = await provider.probe_chat_json()

    assert result["reasoning_disable_requested"] is True
    assert result["reasoning_detected"] is True
    assert result["reasoning_disable_effective"] is False
    assert result["reasoning_tokens"] == 12
    assert result["warning"]
    await provider.http.aclose()


def test_openai_compatible_reasoning_disable_adds_effective_gateway_flag() -> None:
    assert effective_chat_extra_body(
        "openai-compatible",
        {"enable_thinking": False},
    ) == {
        "enable_thinking": False,
        "reasoning_effort": "none",
    }
    assert effective_chat_extra_body(
        "dashscope",
        {"enable_thinking": False},
    ) == {"enable_thinking": False}
    assert (
        effective_chat_extra_body(
            "openai-compatible",
            {"enable_thinking": False, "reasoning_effort": "low"},
        )["reasoning_effort"]
        == "low"
    )


def test_production_allows_plain_http_cloud_model() -> None:
    validate_model_transport(
        "openai-compatible",
        "http://model.example/v1",
        environment="production",
    )
    validate_model_transport(
        "ollama",
        "http://ollama:11434/v1",
        environment="production",
    )
