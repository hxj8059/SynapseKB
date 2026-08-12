import pytest
from synapsekb.agent import tools
from synapsekb.agent.engine import _bounded_messages
from synapsekb.agent.tools import TOOL_SCHEMAS, _safe_calculate


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
        object(),  # type: ignore[arg-type]
    )
    assert calls == [period_a, period_b]
    assert result["period_a"] != result["period_b"]


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
