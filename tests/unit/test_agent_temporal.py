import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from synapsekb.agent.temporal import (
    AgentTimePlan,
    agent_time_context,
    load_agent_time_plan,
    resolve_agent_time_plan,
)

REFERENCE = datetime(2026, 10, 15, 16, 1, 55, tzinfo=UTC)


async def test_time_planning_receives_clock_timezone_and_original_expression() -> None:
    provider = AsyncMock()
    provider.chat_json.return_value = json.dumps(
        {
            "ranges": [
                {
                    "label": "从上周三到昨天",
                    "time_filter": {
                        "from": "2026-10-07T00:00:00+08:00",
                        "to": "2026-10-15T23:59:59.999999+08:00",
                    },
                }
            ]
        }
    )
    plan = await resolve_agent_time_plan(
        provider,
        "从上周三到昨天有哪些变化",
        reference_time=REFERENCE,
        timezone="Asia/Shanghai",
    )
    messages = provider.chat_json.call_args.args[0]
    prompt = json.loads(messages[1]["content"])
    assert prompt == {
        "reference_time": "2026-10-16T00:01:55+08:00",
        "timezone": "Asia/Shanghai",
        "query": "从上周三到昨天有哪些变化",
    }
    assert len(plan.ranges) == 1
    assert plan.ranges[0].time_filter.include_unknown is False
    assert provider.chat_json.call_args.kwargs["disable_reasoning"] is True
    provider.chat_with_tools.assert_not_called()


async def test_query_without_time_intent_produces_no_constraint() -> None:
    provider = AsyncMock()
    provider.chat_json.return_value = '{"ranges":[],"ambiguity":null}'
    plan = await resolve_agent_time_plan(
        provider,
        "介绍半导体行业",
        reference_time=REFERENCE,
        timezone="America/New_York",
    )
    assert plan.ranges == []
    messages = provider.chat_json.call_args.args[0]
    assert json.loads(messages[1]["content"])["reference_time"] == "2026-10-15T12:01:55-04:00"


@pytest.mark.parametrize(
    "response",
    [
        {"content": "not JSON"},
        {"content": "{}"},
        {"content": '{"ranges":[],"ambiguity":"缺少交易日历"}'},
        {"content": json.dumps({"ranges": [{"label": "最近一周", "time_filter": {}}]})},
        {
            "content": json.dumps(
                {
                    "ranges": [
                        {
                            "label": "最近一周",
                            "time_filter": {
                                "from": "2026-10-09T00:00:00",
                                "to": "2026-10-16T00:00:00",
                            },
                        }
                    ]
                }
            )
        },
        {
            "content": json.dumps(
                {
                    "ranges": [
                        {
                            "label": "不存在的短语",
                            "time_filter": {
                                "from": "2026-10-09T00:00:00+08:00",
                            },
                        }
                    ]
                }
            )
        },
    ],
)
async def test_invalid_or_ambiguous_plan_does_not_fall_back_to_unfiltered_search(
    response: dict[str, str],
) -> None:
    provider = AsyncMock()
    provider.chat_json.return_value = response["content"]
    with pytest.raises(ValueError):
        await resolve_agent_time_plan(
            provider,
            "最近一周有哪些机会",
            reference_time=REFERENCE,
            timezone="Asia/Shanghai",
        )


async def test_provider_timeout_or_truncation_does_not_produce_an_empty_plan() -> None:
    provider = AsyncMock()
    provider.chat_json.side_effect = RuntimeError("模型输出达到长度上限")
    with pytest.raises(RuntimeError, match="长度上限"):
        await resolve_agent_time_plan(
            provider,
            "最近一周有哪些机会",
            reference_time=REFERENCE,
            timezone="Asia/Shanghai",
        )


def test_plan_round_trip_preserves_bounds_and_clock_for_retries() -> None:
    plan = AgentTimePlan.model_validate(
        {
            "ranges": [
                {
                    "label": "最近一周",
                    "time_filter": {
                        "from": "2026-10-09T00:01:55+08:00",
                        "to": "2026-10-16T00:01:55+08:00",
                    },
                }
            ]
        }
    )
    saved = {"time_plan": plan.model_dump(mode="json", by_alias=True), "step": 3}
    restored = load_agent_time_plan(saved)
    assert restored == plan
    assert load_agent_time_plan({}) is None
    prompt = agent_time_context(plan, reference_time=REFERENCE, timezone="Asia/Shanghai")
    assert "2026-10-16T00:01:55+08:00" in prompt
    assert "2026-10-09T00:01:55+08:00" in prompt
    assert "不得取消" in prompt
