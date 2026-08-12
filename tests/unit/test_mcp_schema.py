import pytest
from pydantic import ValidationError
from synapsekb.api.schemas import PersonalAccessTokenCreate
from synapsekb.mcp.auth import McpPrincipal, principal_var
from synapsekb.mcp.tools import mcp, tool_session

EXPECTED_TOOLS = {
    "kb_list",
    "kb_get",
    "document_list",
    "document_get",
    "document_download",
    "document_upload",
    "knowledge_search",
    "timeline_search",
    "compare_periods",
    "rag_answer",
    "agent_list",
    "agent_run_start",
    "agent_run_get",
    "agent_run_cancel",
    "wiki_search",
    "wiki_read",
    "wiki_index",
    "wiki_graph_neighbors",
    "wiki_graph_search",
    "wiki_timeline",
}


async def test_mcp_v1_tool_set_is_stable() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert set(tools) == EXPECTED_TOOLS


async def test_mcp_retrieval_tools_expose_scope_and_time_filters() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    for name in {"knowledge_search", "timeline_search", "rag_answer"}:
        properties = tools[name].inputSchema["properties"]
        assert {
            "knowledge_base_ids",
            "document_ids",
            "tag_ids",
            "field",
            "from_time",
            "to_time",
            "include_unknown",
            "top_k",
        } <= set(properties)

    compare_properties = tools["compare_periods"].inputSchema["properties"]
    assert {
        "period_a_from",
        "period_a_to",
        "period_b_from",
        "period_b_to",
        "document_ids",
        "tag_ids",
    } <= set(compare_properties)

    for name in {
        "wiki_index",
        "wiki_search",
        "wiki_graph_search",
        "wiki_graph_neighbors",
        "wiki_timeline",
    }:
        properties = tools[name].inputSchema["properties"]
        assert {"field", "from_time", "to_time", "include_unknown"} <= set(properties)


async def test_mcp_tool_session_requires_authentication() -> None:
    with pytest.raises(PermissionError, match="未认证"):
        async with tool_session("kb:read", "kb_list"):
            pass


async def test_mcp_tool_session_rejects_missing_scope() -> None:
    import uuid

    token = principal_var.set(McpPrincipal(uuid.uuid4(), uuid.uuid4(), frozenset({"kb:read"})))
    try:
        with pytest.raises(PermissionError, match="Scope"):
            async with tool_session("document:write", "document_upload"):
                pass
    finally:
        principal_var.reset(token)


def test_personal_access_token_requires_at_least_one_scope() -> None:
    with pytest.raises(ValidationError):
        PersonalAccessTokenCreate(name="empty", scopes=set())
