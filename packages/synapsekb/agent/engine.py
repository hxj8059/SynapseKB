from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.errors import NodeCancelledError
from langgraph.graph import END, StateGraph
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from synapsekb.agent.tools import TOOL_SCHEMAS, AgentToolContext, execute_tool
from synapsekb.auth.policy import knowledge_base_access_clause
from synapsekb.config import get_settings
from synapsekb.database.models import (
    Agent,
    AgentRun,
    AgentStep,
    KnowledgeBase,
    ProviderModel,
    User,
    agent_knowledge_bases,
)
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.models.provider import DeterministicMockProvider, create_provider
from synapsekb.temporal.parser import resolve_time_ranges


class AgentState(TypedDict):
    messages: list[dict[str, Any]]
    step: int
    final_answer: str | None
    citations: list[dict[str, Any]]


_TOOL_PROTOCOL_RE = re.compile(
    r"(?:<[|｜]{1,2}\s*DSML\s*[|｜]{1,2}\s*(?:tool_calls|invoke))|"
    r"(?:</?(?:tool_calls|function_calls|invoke)(?:\s|>))",
    re.IGNORECASE,
)


def _looks_like_tool_protocol(content: str | None) -> bool:
    """Reject serialized tool requests masquerading as a final answer."""

    return bool(content and _TOOL_PROTOCOL_RE.search(content))


def _final_synthesis_messages(
    messages: list[dict[str, Any]],
    *,
    query: str,
    time_summary: str | None,
    max_chars: int,
) -> list[dict[str, str]]:
    """Flatten tool results so the no-tools turn cannot continue an old call protocol."""

    evidence: list[str] = []
    used = 0
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        excerpt = content[:remaining]
        evidence.append(excerpt)
        used += len(excerpt)
    evidence.reverse()
    evidence_text = "\n\n".join(f"【内部知识证据】\n{content}" for content in evidence)
    return [
        {
            "role": "system",
            "content": (
                "你是 SynapseKB 的最终答案整理器。请仅依据用户问题和已经取得的内部知识证据，"
                "直接输出一份完整、清晰的中文 Markdown 答案。保留证据中的全局 [n] 引用编号；"
                "不得编造 [工具序号:引用序号] 之类的复合编号。证据不足"
                "时明确说明。严禁继续请求任何工具，严禁输出 DSML、XML、JSON、tool_calls、invoke"
                "或函数调用协议，也不要描述隐藏思维过程。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"原始问题：\n{query}\n\n"
                f"时间解析：\n{time_summary or '未识别到明确时间范围。'}\n\n"
                f"已取得的内部知识证据：\n{evidence_text or '没有取得可用证据。'}\n\n"
                "现在直接给出最终答案，不要调用工具。"
            ),
        },
    ]


def _bounded_messages(
    messages: list[dict[str, Any]],
    *,
    max_chars: int,
) -> list[dict[str, Any]]:
    if not messages:
        return []
    system = messages[0] if messages[0].get("role") == "system" else None
    body = messages[1:] if system else messages
    groups: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(body):
        message = body[index]
        group = [message]
        index += 1
        if message.get("role") == "assistant" and message.get("tool_calls"):
            while index < len(body) and body[index].get("role") == "tool":
                group.append(body[index])
                index += 1
        groups.append(group)

    selected_groups: list[list[dict[str, Any]]] = []
    used = len(json.dumps(system, ensure_ascii=False, default=str)) if system else 0
    for group in reversed(groups):
        size = len(json.dumps(group, ensure_ascii=False, default=str))
        if selected_groups and used + size > max_chars:
            break
        selected_groups.append(group)
        used += size
    selected_groups.reverse()
    selected = [message for group in selected_groups for message in group]
    return ([system] if system else []) + selected


def _complete_tool_call_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove declared tool calls that do not have a matching tool response."""

    completed: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        tool_calls = message.get("tool_calls")
        if message.get("role") != "assistant" or not isinstance(tool_calls, list):
            completed.append(message)
            continue
        response_ids: set[str] = set()
        for following in messages[index + 1 :]:
            if following.get("role") != "tool":
                break
            tool_call_id = following.get("tool_call_id")
            if isinstance(tool_call_id, str):
                response_ids.add(tool_call_id)
        completed.append(
            {
                **message,
                "tool_calls": [call for call in tool_calls if str(call.get("id")) in response_ids],
            }
        )
    return completed


async def _publish(redis: Redis, run_id: uuid.UUID, event: str, data: Any) -> None:
    await redis.xadd(
        f"agent:run:{run_id}",
        {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)},
        maxlen=1000,
        approximate=True,
    )


async def run_agent(run_id: uuid.UUID) -> None:
    """Run one Agent with a connection-scoped recovery lock.

    A PostgreSQL advisory lock prevents duplicate broker deliveries from
    executing concurrently. If a worker process dies, PostgreSQL releases the
    lock automatically and a redelivery can resume the persisted graph state,
    even when the row still says ``running``.
    """

    async with AsyncSessionFactory() as lock_session:
        locked = await lock_session.scalar(
            text("SELECT pg_try_advisory_lock(hashtext(:key))").bindparams(
                key=f"agent:{run_id}"
            )
        )
        if not locked:
            return
        try:
            await _run_agent(run_id)
        finally:
            await lock_session.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))").bindparams(
                    key=f"agent:{run_id}"
                )
            )
            await lock_session.commit()


async def _run_agent(run_id: uuid.UUID) -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    async with AsyncSessionFactory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if run is None or run.status in {"completed", "cancelled"}:
            await redis.aclose()
            return
        agent = await session.get(Agent, run.agent_id)
        user = await session.get(User, run.user_id)
        if agent is None or user is None:
            await redis.aclose()
            raise RuntimeError("Agent 或用户不存在")
        model = await session.get(ProviderModel, agent.chat_model_id)
        if model is None or not model.is_enabled:
            await redis.aclose()
            raise RuntimeError("Agent Chat 模型不可用")
        provider = create_provider(model)
        if isinstance(provider, DeterministicMockProvider):
            await provider.close()
            await redis.aclose()
            raise RuntimeError("Mock Provider 不支持 Agent")
        configured_ids = select(agent_knowledge_bases.c.knowledge_base_id).where(
            agent_knowledge_bases.c.agent_id == agent.id
        )
        knowledge_base_ids = list(
            (
                await session.scalars(
                    select(KnowledgeBase.id).where(
                        KnowledgeBase.id.in_(configured_ids),
                        knowledge_base_access_clause(user),
                    )
                )
            ).all()
        )
        if not knowledge_base_ids:
            await provider.close()
            await redis.aclose()
            raise RuntimeError("当前用户无权访问 Agent 配置的任何知识库")
        tool_context = AgentToolContext(session, user, knowledge_base_ids)
        resolved = resolve_time_ranges(run.query, timezone=user.timezone)
        time_summary = "\n".join(item.summary() for item in resolved)
        run.resolved_time_summary = time_summary or None
        run.status = "running"
        run.error_summary = None
        run.finished_at = None
        run.started_at = run.started_at or datetime.now(UTC)
        await session.commit()
        await _publish(redis, run.id, "run.started", {"run_id": str(run.id)})
        if time_summary:
            await _publish(
                redis,
                run.id,
                "thinking.summary",
                {"summary": time_summary},
            )

        initial_state: AgentState
        if run.state_json.get("messages"):
            initial_state = {
                "messages": run.state_json["messages"],
                "step": int(run.state_json.get("step", 0)),
                "final_answer": run.state_json.get("final_answer"),
                "citations": list(run.state_json.get("citations") or run.citations or []),
            }
        else:
            initial_state = {
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"{agent.system_prompt}\n\n"
                            "你只能调用已提供的 SynapseKB 内部只读工具。不得声称访问互联网、"
                            "执行代码或操作外部系统。时间过滤必须用结构化 time_filter；"
                            "跨时期比较必须调用 compare_periods 或分别检索。最终答案必须保留引用。"
                            f"\n\n时间解析摘要：\n{time_summary or '未识别到明确时间范围。'}"
                        ),
                    },
                    {"role": "user", "content": run.query},
                ],
                "step": 0,
                "final_answer": None,
                "citations": [],
            }

        async def check_cancelled() -> None:
            await session.refresh(run)
            if run.cancel_requested_at is not None:
                raise asyncio.CancelledError

        async def persist_state(state: AgentState) -> None:
            run.state_json = {
                "messages": state["messages"],
                "step": state["step"],
                "final_answer": state["final_answer"],
                "citations": state["citations"],
            }
            await session.commit()

        async def model_node(state: AgentState) -> AgentState:
            await check_cancelled()
            use_tools = state["step"] < agent.max_steps
            await _publish(
                redis,
                run.id,
                "thinking.summary",
                {
                    "summary": (
                        "正在选择内部知识工具。"
                        if use_tools
                        else "已达到工具步骤上限，正在基于现有证据作答。"
                    )
                },
            )
            complete_messages = _complete_tool_call_history(state["messages"])
            bounded_messages = _bounded_messages(
                complete_messages,
                max_chars=min(max(agent.max_tokens * 4, 16_000), 120_000),
            )
            if not use_tools:
                bounded_messages = _final_synthesis_messages(
                    complete_messages,
                    query=run.query,
                    time_summary=time_summary or None,
                    max_chars=min(max(agent.max_tokens * 4, 16_000), 80_000),
                )
            output_tokens = (
                min(max(agent.max_tokens, 4_000), 32_000)
                if not use_tools
                else min(max(agent.tool_decision_max_tokens, 1_000), 8_000)
            )
            message = await provider.chat_with_tools(
                bounded_messages,
                TOOL_SCHEMAS,
                max_tokens=output_tokens,
                use_tools=use_tools,
            )
            finish_reason = str(message.pop("_finish_reason", "unknown"))
            usage = message.pop("_usage", {})
            content = str(message.get("content") or "").strip()
            if finish_reason == "length":
                completion_tokens = (
                    usage.get("completion_tokens") if isinstance(usage, dict) else None
                )
                phase = "最终答案" if not use_tools else "工具决策"
                raise RuntimeError(
                    f"Agent {phase}达到输出上限"
                    f"（completion_tokens={completion_tokens or output_tokens}，"
                    f"配置上限={output_tokens}）；结果未标记为完成"
                )
            if not use_tools and (not content or _looks_like_tool_protocol(content)):
                await _publish(
                    redis,
                    run.id,
                    "thinking.summary",
                    {"summary": "模型仍在请求工具，正在强制整理最终答案。"},
                )
                retry_messages = [
                    {
                        **bounded_messages[0],
                        "content": (
                            f"{bounded_messages[0]['content']}\n\n"
                            "上一次回复违反要求并输出了工具协议。这是最后一次整理：首字必须是答案"
                            "正文，不得出现任何尖括号工具标记。"
                        ),
                    },
                    bounded_messages[1],
                ]
                message = await provider.chat_with_tools(
                    retry_messages,
                    [],
                    max_tokens=output_tokens,
                    use_tools=False,
                )
                finish_reason = str(message.pop("_finish_reason", "unknown"))
                usage = message.pop("_usage", {})
                content = str(message.get("content") or "").strip()
                if finish_reason == "length":
                    completion_tokens = (
                        usage.get("completion_tokens") if isinstance(usage, dict) else None
                    )
                    raise RuntimeError(
                        "Agent 最终答案达到输出上限"
                        f"（completion_tokens={completion_tokens or output_tokens}，"
                        f"配置上限={output_tokens}）；结果未标记为完成"
                    )
                if not content or _looks_like_tool_protocol(content):
                    raise RuntimeError(
                        "Agent 已达到工具步骤上限，但模型仍返回工具调用协议，未生成最终答案"
                    )
            elif use_tools and not message.get("tool_calls") and _looks_like_tool_protocol(content):
                raise RuntimeError("模型返回了无法解析的工具调用协议，未生成最终答案")
            if message.get("tool_calls"):
                message = {
                    **message,
                    "tool_calls": message["tool_calls"][: min(3, agent.max_steps - state["step"])],
                }
            messages = [*complete_messages, message]
            final_answer = state["final_answer"]
            if not message.get("tool_calls"):
                final_answer = content or "现有证据不足，无法形成可靠答案。"
                await _publish(
                    redis,
                    run.id,
                    "assistant.delta",
                    {"delta": final_answer},
                )
            next_state: AgentState = {
                "messages": messages,
                "step": state["step"],
                "final_answer": final_answer,
                "citations": state["citations"],
            }
            await persist_state(next_state)
            return next_state

        async def tools_node(state: AgentState) -> AgentState:
            await check_cancelled()
            message = state["messages"][-1]
            messages = list(state["messages"])
            step_number = state["step"]
            citations = list(state["citations"])
            remaining_steps = max(agent.max_steps - step_number, 0)
            selected_tool_calls = message.get("tool_calls", [])[: min(3, remaining_steps)]
            messages[-1] = {**message, "tool_calls": selected_tool_calls}
            for tool_call in selected_tool_calls:
                step_number += 1
                name = tool_call["function"]["name"]
                raw_arguments = tool_call["function"].get("arguments") or "{}"
                argument_error: str | None = None
                try:
                    parsed_arguments = json.loads(raw_arguments)
                    if not isinstance(parsed_arguments, dict):
                        raise ValueError("工具参数必须是 JSON 对象")
                    arguments = parsed_arguments
                except (json.JSONDecodeError, ValueError) as exc:
                    arguments = {}
                    argument_error = f"{type(exc).__name__}: {exc}"
                await _publish(
                    redis,
                    run.id,
                    "tool.started",
                    {"name": name, "arguments": arguments},
                )
                started = asyncio.get_running_loop().time()
                if argument_error is not None:
                    result: Any = {"error": f"工具参数无法解析：{argument_error}"}
                    status = "failed"
                else:
                    try:
                        async with asyncio.timeout(60):
                            result = await execute_tool(name, arguments, tool_context)
                        status = "succeeded"
                    except Exception as exc:
                        result = {"error": f"{type(exc).__name__}: {exc}"}
                        status = "failed"
                duration_ms = int((asyncio.get_running_loop().time() - started) * 1000)
                result, citations, new_citations = _renumber_citations(
                    result,
                    citations,
                )
                output, was_truncated = _bounded_tool_output(
                    result,
                    max_chars=min(12_000, max(agent.max_tokens * 2, 4000)),
                )
                await session.execute(
                    pg_insert(AgentStep)
                    .values(
                        id=uuid.uuid4(),
                        run_id=run.id,
                        ordinal=step_number,
                        kind="tool",
                        status=status,
                        summary=f"调用 {name}",
                        tool_name=name,
                        input_json=arguments,
                        output_summary=output[:2000],
                        duration_ms=duration_ms,
                    )
                    .on_conflict_do_update(
                        index_elements=[AgentStep.run_id, AgentStep.ordinal],
                        set_={
                            "kind": "tool",
                            "status": status,
                            "summary": f"调用 {name}",
                            "tool_name": name,
                            "input_json": arguments,
                            "output_summary": output[:2000],
                            "duration_ms": duration_ms,
                            "updated_at": datetime.now(UTC),
                        },
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": output,
                    }
                )
                await _publish(
                    redis,
                    run.id,
                    "tool.finished",
                    {
                        "name": name,
                        "status": status,
                        "duration_ms": duration_ms,
                        "result_length": len(output),
                        "truncated": was_truncated,
                    },
                )
                if status == "succeeded":
                    for citation in new_citations:
                        await _publish(redis, run.id, "citation", citation)
                await check_cancelled()
            next_state: AgentState = {
                "messages": messages,
                "step": step_number,
                "final_answer": state["final_answer"],
                "citations": citations,
            }
            await persist_state(next_state)
            return next_state

        def route_after_model(state: AgentState) -> str:
            if state["final_answer"] is not None:
                return "end"
            return "tools"

        graph = StateGraph(AgentState)
        graph.add_node("model", model_node)
        graph.add_node("tools", tools_node)
        graph.set_conditional_entry_point(
            lambda state: "tools" if state["messages"][-1].get("tool_calls") else "model",
            {"model": "model", "tools": "tools"},
        )
        graph.add_conditional_edges(
            "model",
            route_after_model,
            {"tools": "tools", "end": END},
        )
        graph.add_edge("tools", "model")
        compiled = graph.compile()
        try:
            async with asyncio.timeout(agent.timeout_seconds):
                final_state = await compiled.ainvoke(
                    initial_state,
                    config={"recursion_limit": agent.max_steps * 2 + 4},
                )
            if not final_state["final_answer"] or _looks_like_tool_protocol(
                final_state["final_answer"]
            ):
                raise RuntimeError("Agent 未生成有效的自然语言最终答案")
            run.result = final_state["final_answer"]
            run.citations = final_state["citations"]
            run.status = "completed"
            run.finished_at = datetime.now(UTC)
            await session.commit()
            await _publish(
                redis,
                run.id,
                "run.completed",
                {"run_id": str(run.id), "steps": final_state["step"]},
            )
        except (asyncio.CancelledError, NodeCancelledError) as exc:
            await session.rollback()
            cancelled_run = await session.get(AgentRun, run_id)
            if cancelled_run is None or cancelled_run.cancel_requested_at is None:
                raise RuntimeError("Agent 模型节点被意外中断") from exc
            cancelled_run.status = "cancelled"
            cancelled_run.error_summary = None
            cancelled_run.finished_at = datetime.now(UTC)
            await session.commit()
            await _publish(redis, run_id, "run.cancelled", {"run_id": str(run_id)})
        except Exception:
            # Leave the last committed graph state intact. The actor decides
            # whether this attempt is retryable and only publishes a terminal
            # failure after the retry budget has been exhausted.
            await session.rollback()
            raise
        finally:
            await provider.close()
            await redis.aclose()


def _bounded_tool_output(value: Any, *, max_chars: int) -> tuple[str, bool]:
    """Bound model context without reparsing a potentially truncated JSON string."""

    output = json.dumps(value, ensure_ascii=False, default=str)
    if len(output) <= max_chars:
        return output, False
    suffix = "\n……（工具结果已按上下文上限截断）"
    return f"{output[: max(max_chars - len(suffix), 0)]}{suffix}", True


def _collect_citations(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        found: list[dict[str, Any]] = []
        for key, item in value.items():
            if key == "citations" and isinstance(item, list):
                found.extend(entry for entry in item if isinstance(entry, dict))
            else:
                found.extend(_collect_citations(item))
        return found
    if isinstance(value, list):
        found = []
        for item in value:
            found.extend(_collect_citations(item))
        return found
    return []


def _citation_identity(citation: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(citation.get("document_id") or ""),
        str(citation.get("chunk_id") or ""),
        str(citation.get("section") or ""),
        str(citation.get("original_text") or "")[:160],
    )


def _renumber_citations(
    value: Any,
    existing: list[dict[str, Any]],
) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]]]:
    """Assign stable run-wide citation numbers inside nested tool results."""

    citations = [dict(item) for item in existing if isinstance(item, dict)]
    number_by_identity = {
        _citation_identity(item): int(item.get("citation_number") or index)
        for index, item in enumerate(citations, 1)
    }
    newly_added: list[dict[str, Any]] = []

    def visit(item: Any) -> Any:
        if isinstance(item, dict):
            copied: dict[str, Any] = {}
            for key, child in item.items():
                if key != "citations" or not isinstance(child, list):
                    copied[key] = visit(child)
                    continue
                numbered: list[Any] = []
                for raw_citation in child:
                    if not isinstance(raw_citation, dict):
                        numbered.append(visit(raw_citation))
                        continue
                    citation = {name: visit(field) for name, field in raw_citation.items()}
                    identity = _citation_identity(citation)
                    number = number_by_identity.get(identity)
                    if number is None:
                        number = len(citations) + 1
                        number_by_identity[identity] = number
                        citation["citation_number"] = number
                        citations.append(citation)
                        newly_added.append(citation)
                    else:
                        citation["citation_number"] = number
                    numbered.append(citation)
                copied[key] = numbered
            return copied
        if isinstance(item, list):
            return [visit(child) for child in item]
        return item

    return visit(value), citations, newly_added
