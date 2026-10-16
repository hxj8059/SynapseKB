import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from synapsekb.agent.final_answer import AgentFinalAnswerError, stream_final_answer


class Provider:
    def __init__(self, scripts: list[tuple[list[str | Exception], str | None]]) -> None:
        self.scripts = scripts
        self.calls: list[dict[str, Any]] = []
        self.last_chat_finish_reason: str | None = None
        self.closed = 0

    async def chat_stream(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        script, finish = self.scripts[len(self.calls) - 1]
        try:
            for event in script:
                if isinstance(event, Exception):
                    raise event
                yield event
            self.last_chat_finish_reason = finish
        finally:
            self.closed += 1


async def generate(provider: Provider, **overrides):
    publish, checkpoint = AsyncMock(), AsyncMock()
    sizes = []

    def make_messages(size):
        sizes.append(size)
        return [{"role": "user", "content": "证据 [1]"}]

    options = dict(
        make_messages=make_messages,
        max_tokens=12_000,
        deadline=asyncio.get_running_loop().time() + 10,
        publish=publish,
        checkpoint=checkpoint,
        check_cancelled=AsyncMock(),
        citation_numbers={1},
    )
    options.update(overrides)
    result = await stream_final_answer(provider, **options)
    return result, publish, checkpoint, sizes


async def test_answer_is_streamed_and_checkpointed_without_sdk_retries() -> None:
    provider = Provider([(["分析", "结论[1]"], "stop")])
    result, publish, checkpoint, sizes = await generate(provider)
    assert result == "分析结论[1]"
    assert sizes == [24_000]
    assert provider.calls[0]["disable_reasoning"] is True
    assert provider.calls[0]["max_retries"] == 0
    assert provider.closed == 1
    assert publish.await_args_list[2].args == ("assistant.delta", {"delta": "分析"})
    assert checkpoint.await_args_list[-1].args == (result,)


@pytest.mark.parametrize(
    "first",
    [
        ([ConnectionError("断流")], None),
        (["未完成"], "length"),
        (["引用错误[99]"], "stop"),
        (["<tool_calls>"], "stop"),
        ([], "stop"),
        (["中断的内容"], None),
    ],
)
async def test_failed_final_attempt_recovers_with_smaller_context(first) -> None:
    provider = Provider([first, (["可靠结论[1]"], "stop")])
    result, publish, checkpoint, sizes = await generate(provider)
    assert result == "可靠结论[1]"
    assert sizes == [24_000, 12_000]
    assert provider.calls[1]["max_tokens"] == 4_000
    assert provider.closed == 2
    assert sum(call.args[0] == "assistant.reset" for call in publish.await_args_list) == 2
    assert checkpoint.await_args_list[-1].args == (result,)


async def test_both_failed_attempts_keep_partial_answer_and_stop_outer_retries() -> None:
    provider = Provider(
        [
            (["已生成的部分内容[1]", ConnectionError("断流")], None),
            ([ConnectionError("再次断流")], None),
        ]
    )
    checkpoint = AsyncMock()
    with pytest.raises(AgentFinalAnswerError, match="最终答案生成失败") as caught:
        await generate(provider, checkpoint=checkpoint)
    assert caught.value.retryable is False
    assert checkpoint.await_args_list[-1].args == ("已生成的部分内容[1]",)
    assert len(provider.calls) == 2


async def test_cancellation_is_not_retried_or_converted_to_success() -> None:
    provider = Provider([])
    with pytest.raises(asyncio.CancelledError):
        await generate(provider, check_cancelled=AsyncMock(side_effect=asyncio.CancelledError))
    assert provider.calls == []


async def test_storage_failure_does_not_trigger_a_second_model_request() -> None:
    provider = Provider([(["回答[1]"], "stop")])
    with pytest.raises(RuntimeError, match="数据库不可用"):
        await generate(provider, checkpoint=AsyncMock(side_effect=RuntimeError("数据库不可用")))
    assert provider.calls == []


async def test_stalled_stream_is_closed_and_recovery_uses_remaining_budget() -> None:
    class StallingProvider(Provider):
        async def chat_stream(self, messages, **kwargs):
            self.calls.append(kwargs)
            try:
                if len(self.calls) == 1:
                    await asyncio.sleep(10)
                yield "恢复完成[1]"
                self.last_chat_finish_reason = "stop"
            finally:
                self.closed += 1

    provider = StallingProvider([])
    result, _, _, _ = await generate(
        provider,
        deadline=asyncio.get_running_loop().time() + 2.2,
    )
    assert result == "恢复完成[1]"
    assert len(provider.calls) == 2
    assert provider.closed == 2
