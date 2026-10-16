"""Stream final answers with bounded, smaller-context recovery."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from typing import Any

from httpx import HTTPError
from openai import OpenAIError

from synapsekb.models.provider import OpenAICompatibleProvider

TOOL_PROTOCOL_RE = re.compile(
    r"(?:<[|｜]{1,2}\s*DSML\s*[|｜]{1,2}\s*(?:tool_calls|invoke))|"
    r"(?:</?(?:tool_calls|function_calls|invoke)(?:\s|>))",
    re.IGNORECASE,
)


class AgentFinalAnswerError(RuntimeError):
    # The final phase already tried a smaller recovery request. Do not schedule
    # another three full attempts with the same saved evidence.
    retryable = False


async def stream_final_answer(
    provider: OpenAICompatibleProvider,
    *,
    make_messages: Callable[[int], list[dict[str, str]]],
    max_tokens: int,
    deadline: float,
    publish: Callable[[str, Any], Awaitable[None]],
    checkpoint: Callable[[str], Awaitable[None]],
    check_cancelled: Callable[[], Awaitable[None]],
    citation_numbers: set[int],
) -> str:
    loop = asyncio.get_running_loop()
    last_error = "未收到模型正文"
    best_partial = ""
    for attempt, context_chars in enumerate((24_000, 12_000)):
        remaining = deadline - loop.time()
        if remaining <= 1:
            break
        await check_cancelled()
        await publish("assistant.reset", {"attempt": attempt + 1})
        await checkpoint("")
        await publish(
            "thinking.summary",
            {
                "summary": (
                    "正在基于已有证据流式生成答案。"
                    if attempt == 0
                    else "答案生成遇到问题，正在缩减证据和输出长度后重试。"
                )
            },
        )
        messages = make_messages(context_chars)
        attempt_deadline = loop.time() + remaining / (2 - attempt)
        content = ""
        pending = ""
        last_emit = last_checkpoint = loop.time()
        try:
            async with asyncio.timeout_at(attempt_deadline):
                async with aclosing(
                    provider.chat_stream(
                        messages,
                        max_tokens=max_tokens if attempt == 0 else min(max_tokens, 4_000),
                        disable_reasoning=True,
                        timeout_seconds=min(30, remaining / (2 - attempt)),
                        max_retries=0,
                    )
                ) as deltas:
                    async for delta in deltas:
                        content += delta
                        pending += delta
                        if TOOL_PROTOCOL_RE.search(content):
                            raise ValueError("模型输出了工具调用协议，没有生成有效答案")
                        current = loop.time()
                        if pending and (current - last_emit >= 0.25 or len(content) == len(delta)):
                            await publish("assistant.delta", {"delta": pending})
                            pending = ""
                            last_emit = current
                        if current - last_checkpoint >= 1:
                            await check_cancelled()
                            await checkpoint(content)
                            last_checkpoint = current
                if pending:
                    await publish("assistant.delta", {"delta": pending})
                if provider.last_chat_finish_reason != "stop":
                    raise ValueError(
                        f"模型输出未完整结束（finish_reason={provider.last_chat_finish_reason}）"
                    )
                if not content.strip():
                    raise ValueError("模型没有返回正文")
                references = {int(number) for number in re.findall(r"\[(\d+)\]", content)}
                if references - citation_numbers:
                    raise ValueError("模型引用了证据中不存在的编号")
                await checkpoint(content)
                return content.strip()
        except (TimeoutError, ValueError) as exc:
            last_error = str(exc) or "模型在本轮答案生成时间内未完成输出"
        except (OpenAIError, HTTPError, ConnectionError) as exc:
            # Model transport exceptions are safe to retry once with a smaller
            # request. CancelledError remains outside this handler.
            last_error = f"模型请求异常（{type(exc).__name__}）"
        partial_references = {int(number) for number in re.findall(r"\[(\d+)\]", content)}
        if (
            len(content) > len(best_partial)
            and not TOOL_PROTOCOL_RE.search(content)
            and partial_references <= citation_numbers
        ):
            best_partial = content
        await publish("thinking.summary", {"summary": f"最终答案生成未完成：{last_error}"})
    await checkpoint(best_partial)
    raise AgentFinalAnswerError(
        f"Agent 最终答案生成失败，已尝试流式生成及缩减上下文恢复：{last_error}。"
        "已保留检索步骤和已生成的部分内容，未将不完整答案标记为完成。"
    )
