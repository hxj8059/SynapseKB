import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from synapsekb.agent import tools
from synapsekb.agent.engine import _bounded_messages
from synapsekb.agent.tools import TOOL_SCHEMAS, _safe_calculate
from synapsekb.api.schemas import TimeFilter
from synapsekb.database.models import Document, User


def tool_context(*filters: TimeFilter) -> tools.AgentToolContext:
    return tools.AgentToolContext(AsyncMock(), User(), [], filters)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2 * 3", 7),
        ("10 // 3", 3),
        ("2 ** 8", 256),
        ("-4 + 1.5", -2.5),
    ],
)
def test_safe_calculate_allows_basic_arithmetic(
    expression: str,
    expected: int | float,
) -> None:
    assert _safe_calculate(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "open('/etc/passwd')",
        "2 ** 11",
        "x + 1",
    ],
)
def test_safe_calculate_rejects_code_and_unbounded_power(expression: str) -> None:
    with pytest.raises(ValueError):
        _safe_calculate(expression)


def test_agent_exposes_only_internal_read_and_safe_utility_tools() -> None:
    names = {item["function"]["name"] for item in TOOL_SCHEMAS}
    assert names == {
        "knowledge_search",
        "document_read",
        "wiki_search",
        "wiki_read",
        "wiki_graph_search",
        "timeline_search",
        "compare_periods",
        "calculator",
        "current_time",
    }
    assert not names & {"web_search", "shell", "python", "browser", "mcp_install"}


async def test_compare_periods_executes_two_independent_searches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_search(
        context: object,
        query: str,
        time_filter: dict[str, object] | None,
        top_k: int,
        document_ids: list[str] | None = None,
        tag_ids: list[str] | None = None,
    ) -> dict[str, object]:
        del context, query, top_k, document_ids, tag_ids
        calls.append(time_filter or {})
        return {"time_filter": time_filter, "citations": []}

    monkeypatch.setattr(tools, "_search", fake_search)
    monkeypatch.setattr(tools, "_authorize_context", AsyncMock())
    period_a = {
        "field": "source_time",
        "from": "2023-01-01T00:00:00+08:00",
        "to": "2023-12-31T23:59:59+08:00",
        "include_unknown": False,
    }
    period_b = {
        "field": "source_time",
        "from": "2025-01-01T00:00:00+08:00",
        "to": "2025-12-31T23:59:59+08:00",
        "include_unknown": False,
    }
    result = await tools.execute_tool(
        "compare_periods",
        {
            "query": "政策变化",
            "period_a": period_a,
            "period_b": period_b,
            "top_k": 10,
        },
        tool_context(),
    )
    assert calls == [period_a, period_b]
    assert result["period_a"] != result["period_b"]


@pytest.fixture
def required_filter() -> TimeFilter:
    return TimeFilter.model_validate(
        {
            "from": "2026-10-09T00:01:55+08:00",
            "to": "2026-10-16T00:01:55+08:00",
        }
    )


@pytest.mark.parametrize(
    "name",
    [
        "knowledge_search",
        "timeline_search",
        "wiki_search",
        "wiki_graph_search",
    ],
)
@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {
            "field": "created_at",
            "include_unknown": True,
        },
    ],
)
def test_search_cannot_drop_or_change_user_time_constraint(
    name: str,
    raw: object,
    required_filter: TimeFilter,
) -> None:
    result = tools.prepare_tool_arguments(
        name,
        {"query": "投资机会", "time_filter": raw},
        tool_context(required_filter),
    )
    assert TimeFilter.model_validate(result["time_filter"]) == required_filter


async def test_search_receives_object_filter_when_model_sends_json_string(
    monkeypatch: pytest.MonkeyPatch,
    required_filter: TimeFilter,
) -> None:
    search = AsyncMock(return_value={"citations": []})
    monkeypatch.setattr(tools, "_search", search)
    monkeypatch.setattr(tools, "_authorize_context", AsyncMock())
    await tools.execute_tool(
        "knowledge_search",
        {
            "query": "投资机会",
            "time_filter": required_filter.model_dump_json(by_alias=True),
        },
        tool_context(required_filter),
    )
    assert TimeFilter.model_validate(search.call_args.args[2]) == required_filter


def test_model_can_narrow_but_cannot_expand_time_range(required_filter: TimeFilter) -> None:
    raw = {
        "from": "2026-10-01T00:00:00+08:00",
        "to": "2026-10-12T00:00:00+08:00",
        "include_unknown": True,
    }
    result = tools.prepare_tool_arguments(
        "knowledge_search",
        {"time_filter": json.dumps(raw)},
        tool_context(required_filter),
    )
    effective = TimeFilter.model_validate(result["time_filter"])
    assert effective.from_ == required_filter.from_
    assert effective.to == datetime.fromisoformat(raw["to"])
    assert effective.include_unknown is False


def test_disjoint_time_filter_is_rejected(required_filter: TimeFilter) -> None:
    with pytest.raises(ValueError):
        tools.prepare_tool_arguments(
            "knowledge_search",
            {
                "time_filter": {
                    "to": "2026-09-18T00:00:00+08:00",
                }
            },
            tool_context(required_filter),
        )


def test_comparison_requires_independent_periods(required_filter: TimeFilter) -> None:
    earlier = TimeFilter.model_validate(
        {
            "from": "2026-09-01T00:00:00+08:00",
            "to": "2026-09-30T23:59:59+08:00",
        }
    )
    context = tool_context(earlier, required_filter)
    with pytest.raises(ValueError, match="多个时期"):
        tools.prepare_tool_arguments("wiki_search", {"query": "比较"}, context)
    with pytest.raises(ValueError, match="独立时期"):
        tools.prepare_tool_arguments(
            "knowledge_search",
            {
                "time_filter": {
                    "from": "2026-09-01T00:00:00+08:00",
                    "to": "2026-10-16T00:01:55+08:00",
                }
            },
            context,
        )
    result = tools.prepare_tool_arguments(
        "compare_periods",
        {
            "period_a": earlier.model_dump(mode="json", by_alias=True),
            "period_b": required_filter.model_dump(mode="json", by_alias=True),
        },
        context,
    )
    assert TimeFilter.model_validate(result["period_a"]) == earlier
    assert TimeFilter.model_validate(result["period_b"]) == required_filter


@pytest.mark.parametrize("timestamp", [None, "2026-09-18T00:00:00+08:00"])
def test_read_cannot_reintroduce_out_of_range_evidence(
    timestamp: str | None,
    required_filter: TimeFilter,
) -> None:
    document = Document(source_time=datetime.fromisoformat(timestamp) if timestamp else None)
    with pytest.raises(ValueError, match="时间范围"):
        tools._check_read_time(document, (required_filter,))


def test_no_temporal_intent_keeps_search_unfiltered() -> None:
    result = tools.prepare_tool_arguments("knowledge_search", {"query": "介绍行业"}, tool_context())
    assert result["time_filter"] is None


def test_agent_context_keeps_system_and_recent_messages_within_bound() -> None:
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "old" * 100},
        {"role": "assistant", "content": "recent"},
        {"role": "user", "content": "latest"},
    ]
    bounded = _bounded_messages(messages, max_chars=180)
    assert bounded[0] == messages[0]
    assert bounded[-1] == messages[-1]
    assert messages[1] not in bounded
