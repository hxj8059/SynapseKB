from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
import structlog
from openai import AsyncOpenAI
from redis.asyncio import Redis

from synapsekb.auth.security import decrypt_secret
from synapsekb.config import get_settings
from synapsekb.database.models import ProviderModel

logger = structlog.get_logger()


def normalize_model_base_url(kind: str, base_url: str) -> str:
    """Accept either an API root or the full operation endpoint.

    OpenAI-compatible clients append their own operation path. Vendor examples
    commonly show the full ``/embeddings`` URL, which would otherwise become
    ``/embeddings/embeddings``.
    """

    normalized = base_url.rstrip("/")
    suffixes = {
        "embedding": ("/embeddings",),
        "rerank": ("/rerank", "/reranks"),
        "chat": ("/chat/completions",),
    }
    for suffix in suffixes.get(kind, ()):
        if normalized.lower().endswith(suffix):
            return normalized[: -len(suffix)].rstrip("/")
    return normalized


def embedding_dimension_request_mode(model: ProviderModel) -> bool | None:
    """Return True/False for an explicit choice, or None for auto detection."""

    configured = model.config.get("embedding_send_dimensions")
    if isinstance(configured, bool):
        return configured
    host = urlsplit(normalize_model_base_url(model.kind, model.base_url)).hostname or ""
    if host.casefold() == "tokenhub.tencentmaas.com":
        return False
    return None


def reasoning_disable_requested(extra_body: dict[str, Any]) -> bool:
    thinking = extra_body.get("thinking")
    return (
        extra_body.get("enable_thinking") is False
        or extra_body.get("reasoning_effort") == "none"
        or (isinstance(thinking, dict) and thinking.get("type") == "disabled")
    )


def effective_chat_extra_body(
    provider: str,
    configured: dict[str, Any],
) -> dict[str, Any]:
    """Add the tested no-reasoning flag for generic compatible gateways.

    Some gateways accept ``enable_thinking=false`` but silently ignore it.
    SynapseKB's configured OpenAI-compatible gateway was probed to honor
    ``reasoning_effort=none``. Explicit administrator values always win.
    """

    effective = dict(configured)
    if provider == "openai-compatible" and effective.get("enable_thinking") is False:
        effective.setdefault("reasoning_effort", "none")
    return effective


def provider_presets() -> dict[str, dict[str, str]]:
    return {
        "openai": {"base_url": "https://api.openai.com/v1"},
        "deepseek": {"base_url": "https://api.deepseek.com/v1"},
        "dashscope": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        "ollama": {"base_url": "http://host.docker.internal:11434/v1"},
        "openai-compatible": {"base_url": ""},
    }


@dataclass(frozen=True, slots=True)
class ModelUsage:
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout_seconds: int = 60,
        max_concurrency: int = 5,
        rerank_path: str = "/rerank",
        embedding_dimensions: int | None = None,
        embedding_batch_size: int = 64,
        embedding_send_dimensions: bool | None = None,
        embedding_encoding_format: str | None = None,
        chat_extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_concurrency = max_concurrency
        self.rerank_path = f"/{rerank_path.lstrip('/')}"
        self.embedding_dimensions = embedding_dimensions
        self.embedding_batch_size = embedding_batch_size
        self.embedding_send_dimensions = embedding_send_dimensions
        self.embedding_encoding_format = embedding_encoding_format
        self.chat_extra_body = dict(chat_extra_body or {})
        self.base_url_host = (urlsplit(base_url).hostname or "").casefold()
        # Provider instances are request-scoped. Keeping the final stream
        # metadata here lets callers reject a truncated stream instead of
        # silently persisting it as a completed answer.
        self.last_chat_finish_reason: str | None = None
        self.last_chat_usage: dict[str, int | None] = {}
        quota_digest = hashlib.sha256(f"{base_url}|{model_name}".encode()).hexdigest()[:24]
        self.quota_key = f"quota:model:{quota_digest}"
        self.client = AsyncOpenAI(
            api_key=api_key or "not-required",
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=2,
        )
        self.http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=timeout_seconds,
        )

    @asynccontextmanager
    async def quota(self) -> AsyncIterator[None]:
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        acquired = False
        acquire_script = """
        local value = redis.call('INCR', KEYS[1])
        if value == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
        return value
        """
        release_script = """
        local value = tonumber(redis.call('GET', KEYS[1]) or '0')
        if value > 0 then return redis.call('DECR', KEYS[1]) end
        return 0
        """
        try:
            while True:
                current = int(
                    await redis.eval(
                        acquire_script,
                        1,
                        self.quota_key,
                        max(self.timeout_seconds * 2, 120),
                    )
                )
                if current <= self.max_concurrency:
                    acquired = True
                    break
                await redis.eval(release_script, 1, self.quota_key)
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("模型并发配额等待超时")
                await asyncio.sleep(0.05)
            yield
        finally:
            if acquired:
                await redis.eval(release_script, 1, self.quota_key)
            await redis.aclose()

    async def close(self) -> None:
        await self.client.close()
        await self.http.aclose()

    async def embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        started = time.perf_counter()
        vectors: list[list[float]] = []
        total_tokens = 0
        for start in range(0, len(texts), self.embedding_batch_size):
            params: dict[str, Any] = {
                "model": self.model_name,
                "input": list(texts[start : start + self.embedding_batch_size]),
            }
            if (
                self.embedding_dimensions is not None
                and self.embedding_send_dimensions is not False
            ):
                params["dimensions"] = self.embedding_dimensions
            if self.embedding_encoding_format is not None:
                params["encoding_format"] = self.embedding_encoding_format
            for _attempt in range(3):
                try:
                    async with self.quota():
                        response = await self.client.embeddings.create(**params)
                    break
                except Exception as exc:
                    error_text = str(getattr(exc, "body", exc)).casefold()
                    if (
                        "dimensions" in params
                        and self.embedding_send_dimensions is None
                        and "dimension" in error_text
                    ):
                        params.pop("dimensions")
                        self.embedding_send_dimensions = False
                        continue
                    if "encoding_format" in params and "encoding" in error_text:
                        params.pop("encoding_format")
                        self.embedding_encoding_format = None
                        continue
                    raise
            else:  # pragma: no cover - loop always breaks or raises
                raise RuntimeError("Embedding 参数兼容重试失败")
            vectors.extend(
                item.embedding for item in sorted(response.data, key=lambda item: item.index)
            )
            total_tokens += int(getattr(response.usage, "total_tokens", 0) or 0)
        logger.info(
            "model_call",
            operation="embedding",
            model=self.model_name,
            item_count=len(texts),
            latency_ms=int((time.perf_counter() - started) * 1000),
            total_tokens=total_tokens,
        )
        return vectors

    async def chat_stream(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        started = time.perf_counter()
        self.last_chat_finish_reason = None
        self.last_chat_usage = {}
        async with self.quota():
            params: Any = {
                "model": self.model_name,
                "messages": list(messages),
                "max_tokens": max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if self.chat_extra_body:
                params["extra_body"] = self.chat_extra_body
            stream: Any = await self.client.chat.completions.create(
                **params,
            )
            async for event in stream:
                choice = event.choices[0] if event.choices else None
                delta = choice.delta.content if choice is not None else None
                if delta:
                    yield delta
                if choice is not None and choice.finish_reason is not None:
                    self.last_chat_finish_reason = str(choice.finish_reason)
                usage = getattr(event, "usage", None)
                if usage is not None:
                    self.last_chat_usage = {
                        "prompt_tokens": getattr(usage, "prompt_tokens", None),
                        "completion_tokens": getattr(usage, "completion_tokens", None),
                    }
        logger.info(
            "model_call",
            operation="chat_stream",
            model=self.model_name,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=self.last_chat_finish_reason,
            **self.last_chat_usage,
        )

    async def chat_json(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int,
        disable_reasoning: bool = False,
    ) -> str:
        """Request a complete JSON object without exposing reasoning fields.

        Reasoning-capable OpenAI-compatible models may spend part of their output
        budget in ``reasoning_content`` before producing the final ``content``.
        A non-streaming JSON response gives the gateway enough information to
        enforce a complete object and lets us reject truncated/empty answers.
        """

        started = time.perf_counter()
        response = await self._request_chat_json(
            messages,
            max_tokens=max_tokens,
            disable_reasoning=disable_reasoning,
        )
        if not response.choices:
            raise RuntimeError("模型没有返回任何候选结果")
        choice = response.choices[0]
        content = str(choice.message.content or "").strip()
        finish_reason = str(getattr(choice, "finish_reason", "unknown"))
        reasoning_content = str(getattr(choice.message, "reasoning_content", "") or "")
        completion_details = getattr(response.usage, "completion_tokens_details", None)
        reasoning_tokens = getattr(completion_details, "reasoning_tokens", None)
        completion_tokens = getattr(response.usage, "completion_tokens", None)
        prompt_tokens = getattr(response.usage, "prompt_tokens", None)
        request_extra_body = self._chat_json_extra_body(disable_reasoning)
        disable_requested = reasoning_disable_requested(request_extra_body)
        logger.info(
            "model_call",
            operation="chat_json",
            model=self.model_name,
            latency_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            reasoning_chars=len(reasoning_content),
            reasoning_disable_requested=disable_requested,
            finish_reason=finish_reason,
            content_chars=len(content),
        )
        if finish_reason == "length":
            detail = f"completion_tokens={completion_tokens}"
            if reasoning_tokens is not None:
                detail += f"，reasoning_tokens={reasoning_tokens}"
            raise RuntimeError(f"模型输出达到长度上限（{detail}）；兼容网关可能未执行关闭推理参数")
        if not content:
            raise RuntimeError(f"模型没有返回最终内容（finish_reason={finish_reason}）")
        return content

    async def _request_chat_json(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int,
        disable_reasoning: bool = False,
    ) -> Any:
        async with self.quota():
            params: Any = {
                "model": self.model_name,
                "messages": list(messages),
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
            extra_body = self._chat_json_extra_body(disable_reasoning)
            if extra_body:
                params["extra_body"] = extra_body
            # Wiki/health callers already implement schema-aware recovery. A
            # client-level retry would repeat the same long structured prompt
            # two more times before the smaller recovery batch can run.
            client = (
                self.client.with_options(max_retries=0)
                if hasattr(self.client, "with_options")
                else self.client
            )
            return await client.chat.completions.create(**params)

    def _chat_json_extra_body(self, disable_reasoning: bool) -> dict[str, Any]:
        extra_body = dict(self.chat_extra_body)
        if not disable_reasoning or reasoning_disable_requested(extra_body):
            return extra_body
        if self.base_url_host == "tokenhub.tencentmaas.com":
            # Tencent MaaS accepts the Anthropic-compatible thinking switch;
            # unlike enable_thinking=false it actually removes reasoning tokens
            # for DeepSeek structured-output requests.
            extra_body["thinking"] = {"type": "disabled"}
        elif self.base_url_host.endswith("dashscope.aliyuncs.com"):
            extra_body["enable_thinking"] = False
        return extra_body

    async def probe_chat_json(self) -> dict[str, Any]:
        """Check structured-output and reasoning-control behavior without logging content."""

        response = await self._request_chat_json(
            [{"role": "user", "content": '只返回 JSON 对象：{"ok":true}'}],
            max_tokens=512,
        )
        if not response.choices:
            raise RuntimeError("模型没有返回任何候选结果")
        choice = response.choices[0]
        message = choice.message
        content = str(message.content or "").strip()
        reasoning_content = str(getattr(message, "reasoning_content", "") or "")
        completion_details = getattr(response.usage, "completion_tokens_details", None)
        reasoning_tokens = getattr(completion_details, "reasoning_tokens", None)
        disable_requested = reasoning_disable_requested(self.chat_extra_body)
        reasoning_detected = bool(reasoning_content) or bool(reasoning_tokens)
        return {
            "finish_reason": str(getattr(choice, "finish_reason", "unknown")),
            "content_present": bool(content),
            "prompt_tokens": getattr(response.usage, "prompt_tokens", None),
            "completion_tokens": getattr(response.usage, "completion_tokens", None),
            "reasoning_tokens": reasoning_tokens,
            "reasoning_detected": reasoning_detected,
            "reasoning_disable_requested": disable_requested,
            "reasoning_disable_effective": disable_requested and not reasoning_detected,
            "warning": (
                "网关仍返回 reasoning token，关闭推理参数未生效"
                if disable_requested and reasoning_detected
                else None
            ),
        }

    async def chat_with_tools(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        use_tools: bool = True,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        async with self.quota():
            params: Any = {
                "model": self.model_name,
                "messages": list(messages),
                "max_tokens": max_tokens,
            }
            if use_tools:
                params["tools"] = list(tools)
                params["tool_choice"] = "auto"
            if self.chat_extra_body:
                params["extra_body"] = self.chat_extra_body
            response: Any = await self.client.chat.completions.create(**params)
        if not response.choices:
            raise RuntimeError("模型没有返回任何候选结果")
        choice = response.choices[0]
        message = choice.message
        finish_reason = str(getattr(choice, "finish_reason", "unknown"))
        usage = {
            "prompt_tokens": getattr(response.usage, "prompt_tokens", None),
            "completion_tokens": getattr(response.usage, "completion_tokens", None),
        }
        logger.info(
            "model_call",
            operation="chat_tools",
            model=self.model_name,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=finish_reason,
            **usage,
        )
        return {
            **cast(dict[str, Any], message.model_dump(exclude_none=True)),
            "_finish_reason": finish_reason,
            "_usage": usage,
        }

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int,
    ) -> list[tuple[int, float]]:
        started = time.perf_counter()
        async with self.quota():
            response = await self.http.post(
                self.rerank_path,
                json={
                    "model": self.model_name,
                    "query": query,
                    "documents": list(documents),
                    "top_n": top_n,
                },
            )
            response.raise_for_status()
        payload: dict[str, Any] = response.json()
        logger.info(
            "model_call",
            operation="rerank",
            model=self.model_name,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return [
            (int(result["index"]), float(result["relevance_score"]))
            for result in payload["results"]
        ]

    async def test_embedding_dimension(self) -> int:
        embeddings = await self.embeddings(["SynapseKB 连接测试"])
        if len(embeddings) != 1 or not embeddings[0]:
            raise RuntimeError("Embedding provider returned no vector")
        return len(embeddings[0])


class DeterministicMockProvider:
    """Explicit test-only provider. Never selected unless provider is `mock`."""

    def __init__(self, dimensions: int = 1536) -> None:
        self.dimensions = dimensions

    async def embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            vector = [(digest[index % len(digest)] / 127.5) - 1 for index in range(self.dimensions)]
            vectors.append(vector)
        return vectors

    async def close(self) -> None:
        return None


def create_provider(
    model: ProviderModel,
    *,
    embedding_dimensions: int | None = None,
) -> OpenAICompatibleProvider | DeterministicMockProvider:
    requested_dimensions = embedding_dimensions or model.embedding_dimensions
    if model.provider == "mock":
        return DeterministicMockProvider(requested_dimensions or 1536)
    base_url = normalize_model_base_url(model.kind, model.base_url)
    validate_model_transport(model.provider, base_url)
    api_key = (
        decrypt_secret(model.encrypted_api_key, context=f"model:{model.name}")
        if model.encrypted_api_key
        else ""
    )
    raw_chat_extra_body = model.config.get("chat_extra_body")
    configured_chat_extra_body = (
        raw_chat_extra_body if isinstance(raw_chat_extra_body, dict) else {}
    )
    chat_extra_body = effective_chat_extra_body(
        model.provider,
        configured_chat_extra_body,
    )
    embedding_send_dimensions = embedding_dimension_request_mode(model)
    encoding_format_config = model.config.get("embedding_encoding_format")
    embedding_encoding_format = (
        str(encoding_format_config)
        if isinstance(encoding_format_config, str) and encoding_format_config
        else "float"
    )
    return OpenAICompatibleProvider(
        api_key=api_key,
        base_url=base_url,
        model_name=model.model_name,
        timeout_seconds=model.timeout_seconds,
        max_concurrency=model.max_concurrency,
        rerank_path=str(
            model.config.get("rerank_path")
            or ("/reranks" if model.provider == "dashscope" else "/rerank")
        ),
        embedding_dimensions=requested_dimensions,
        embedding_batch_size=int(
            model.config.get("embedding_batch_size")
            or (20 if model.provider == "dashscope" else 64)
        ),
        embedding_send_dimensions=embedding_send_dimensions,
        embedding_encoding_format=embedding_encoding_format,
        chat_extra_body=chat_extra_body,
    )


def validate_model_transport(
    provider: str,
    base_url: str,
    *,
    environment: str | None = None,
) -> None:
    runtime_environment = environment or get_settings().environment
    parsed = urlsplit(base_url)
    if (
        runtime_environment == "production"
        and provider != "ollama"
        and parsed.scheme != "https"
    ):
        # Some private model gateways are only reachable over a trusted VPC.
        # Keep this deployment option available, but make the transport risk
        # visible without logging credentials, query parameters or prompts.
        logger.warning(
            "insecure_model_transport_allowed",
            provider=provider,
            scheme=parsed.scheme,
            host=parsed.hostname,
            port=parsed.port,
        )
