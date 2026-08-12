from synapsekb.agent.engine import (
    _bounded_messages,
    _bounded_tool_output,
    _collect_citations,
    _complete_tool_call_history,
    _final_synthesis_messages,
    _looks_like_tool_protocol,
    _renumber_citations,
)


def test_bounded_messages_keeps_assistant_tool_exchange_atomic() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "old", "function": {"name": "search"}}],
        },
        {"role": "tool", "tool_call_id": "old", "content": "x" * 300},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "new-1", "function": {"name": "read"}},
                {"id": "new-2", "function": {"name": "read"}},
            ],
        },
        {"role": "tool", "tool_call_id": "new-1", "content": "y" * 300},
        {"role": "tool", "tool_call_id": "new-2", "content": "z" * 300},
    ]

    bounded = _bounded_messages(messages, max_chars=750)

    assert [message["role"] for message in bounded] == [
        "system",
        "assistant",
        "tool",
        "tool",
    ]
    assert [message.get("tool_call_id") for message in bounded[-2:]] == [
        "new-1",
        "new-2",
    ]


def test_truncated_tool_output_keeps_citations_available_from_original_result() -> None:
    result = {
        "count": 20,
        "citations": [
            {
                "citation_number": 1,
                "document_id": "document-1",
                "original_text": "来源内容",
            }
        ],
        "content": "存储行业分析" * 2_000,
    }

    output, truncated = _bounded_tool_output(result, max_chars=500)

    assert truncated is True
    assert len(output) <= 500
    assert "工具结果已按上下文上限截断" in output
    assert _collect_citations(result) == result["citations"]


def test_small_tool_output_remains_valid_json() -> None:
    output, truncated = _bounded_tool_output({"count": 1}, max_chars=500)

    assert truncated is False
    assert output == '{"count": 1}'


def test_incomplete_tool_calls_are_removed_from_persisted_history() -> None:
    messages = [
        {"role": "user", "content": "分析存储行业"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-1", "function": {"name": "knowledge_search"}},
                {"id": "call-2", "function": {"name": "wiki_search"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "{}"},
    ]

    repaired = _complete_tool_call_history(messages)

    assert [call["id"] for call in repaired[1]["tool_calls"]] == ["call-1"]


def test_dsml_tool_request_is_not_a_final_answer() -> None:
    content = """<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name=\"wiki_search\">查询</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>"""

    assert _looks_like_tool_protocol(content) is True
    assert _looks_like_tool_protocol("台湾存储产业链的核心公司包括……[1]") is False


def test_final_synthesis_flattens_tool_roles_and_excludes_assistant_protocol() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "function": {"name": "search"}}],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "来源证据 [1]"},
        {"role": "assistant", "content": "<｜｜DSML｜｜tool_calls>"},
    ]

    synthesis = _final_synthesis_messages(
        messages,
        query="总结产业链",
        time_summary=None,
        max_chars=1_000,
    )

    assert [message["role"] for message in synthesis] == ["system", "user"]
    assert "来源证据 [1]" in synthesis[1]["content"]
    assert "<｜｜DSML｜｜tool_calls>" not in synthesis[1]["content"]


def test_agent_citations_are_deduplicated_and_numbered_across_tools() -> None:
    first = {
        "citations": [
            {
                "citation_number": 1,
                "document_id": "document-1",
                "chunk_id": "chunk-1",
                "section": "结论",
                "original_text": "第一条证据",
            }
        ]
    }
    numbered_first, citations, added = _renumber_citations(first, [])
    second = {
        "period_a": {
            "citations": [
                first["citations"][0],
                {
                    "citation_number": 1,
                    "document_id": "document-2",
                    "chunk_id": "chunk-2",
                    "section": "趋势",
                    "original_text": "第二条证据",
                },
            ]
        }
    }
    numbered_second, citations, second_added = _renumber_citations(second, citations)

    assert numbered_first["citations"][0]["citation_number"] == 1
    assert [item["citation_number"] for item in numbered_second["period_a"]["citations"]] == [
        1,
        2,
    ]
    assert len(citations) == 2
    assert len(added) == 1
    assert len(second_added) == 1
