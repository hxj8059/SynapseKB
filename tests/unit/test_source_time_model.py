from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from synapsekb.temporal.source_time_model import (
    SOURCE_TIME_CONTEXT_MAX_CHARS,
    extract_source_time_with_model,
    select_source_time_context,
)


class FakeJsonProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.messages: Sequence[dict[str, str]] = []
        self.max_tokens = 0
        self.disable_reasoning = False

    async def chat_json(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int,
        disable_reasoning: bool = False,
    ) -> str:
        self.messages = messages
        self.max_tokens = max_tokens
        self.disable_reasoning = disable_reasoning
        return self.response


def test_context_uses_only_first_logical_page_and_is_bounded() -> None:
    content = (
        "<!-- page:1 -->\n第一页开头 2026-07-03\n"
        + "中间正文" * 500
        + "\n第一页末尾报告日期 2026-07-04\n"
        "<!-- page:2 -->\n第二页不应发送 2025-01-01"
    )
    context = select_source_time_context(content)
    assert "第一页开头" in context
    assert "第一页末尾报告日期" in context
    assert "第二页不应发送" not in context
    assert len(context) == SOURCE_TIME_CONTEXT_MAX_CHARS
    assert len(select_source_time_context("正文" * 10_000)) == SOURCE_TIME_CONTEXT_MAX_CHARS


async def test_model_extracts_date_with_verifiable_evidence() -> None:
    provider = FakeJsonProvider(
        '{"source_time":"2026-07-03","evidence":"报告日期：2026-07-03","reason":"封面报告日期"}'
    )
    result = await extract_source_time_with_model(
        provider,
        filename="weekly-report.pdf",
        title="Weekly report",
        content="<!-- page:1 -->\n报告日期：2026-07-03\n正文",
    )

    assert result.value == datetime(2026, 7, 3, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert provider.max_tokens == 1024
    assert provider.disable_reasoning is True
    assert "weekly-report.pdf" in provider.messages[1]["content"]


async def test_model_can_keep_unknown_source_time() -> None:
    provider = FakeJsonProvider(
        '{"source_time":null,"evidence":null,"reason":"存在多个相互冲突的日期"}'
    )
    result = await extract_source_time_with_model(
        provider,
        filename="comparison.pdf",
        title="年度对比",
        content="2024-01-01 与 2025-01-01",
    )
    assert result.value is None


async def test_model_rejects_hallucinated_evidence() -> None:
    provider = FakeJsonProvider(
        '{"source_time":"2026-07-03","evidence":"报告日期：2026-07-03","reason":"报告日期"}'
    )
    with pytest.raises(ValueError, match="证据不在输入材料中"):
        await extract_source_time_with_model(
            provider,
            filename="report.pdf",
            title="没有日期",
            content="正文也没有日期",
        )


async def test_model_rejects_date_not_supported_by_evidence() -> None:
    provider = FakeJsonProvider(
        '{"source_time":"2026-07-03","evidence":"报告日期：2026-08-04","reason":"报告日期"}'
    )
    with pytest.raises(ValueError, match="不支持返回的完整日期"):
        await extract_source_time_with_model(
            provider,
            filename="report.pdf",
            title="报告",
            content="报告日期：2026-08-04",
        )


async def test_model_accepts_english_cover_date() -> None:
    provider = FakeJsonProvider(
        '{"source_time":"2026-07-03","evidence":"Report date: July 3, 2026","reason":"cover date"}'
    )
    result = await extract_source_time_with_model(
        provider,
        filename="report.pdf",
        title="Weekly report",
        content="Report date: July 3, 2026",
    )
    assert result.value == datetime(2026, 7, 3, tzinfo=ZoneInfo("Asia/Shanghai"))


async def test_model_rejects_malformed_json() -> None:
    provider = FakeJsonProvider("source_time is 2026-07-03")
    with pytest.raises(ValueError, match="没有返回 JSON 对象"):
        await extract_source_time_with_model(
            provider,
            filename="report.pdf",
            title="报告",
            content="2026-07-03",
        )
