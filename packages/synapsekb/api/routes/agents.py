from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import ColumnElement, and_, exists, func, or_, select, true

from apps.agent_runner.actors import execute_agent_run
from synapsekb.api.schemas import (
    AgentCreate,
    AgentRead,
    AgentRunCreate,
    AgentRunHistoryRead,
    AgentRunRead,
    AgentRunSummaryRead,
    AgentRuntimeUpdate,
)
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import require_admin
from synapsekb.config import get_settings
from synapsekb.database.models import (
    Agent,
    AgentRun,
    AgentStep,
    AuditLog,
    ChatSession,
    KnowledgeBase,
    ProviderModel,
    User,
    agent_knowledge_bases,
    agent_users,
)

router = APIRouter()


async def _validate_agent_config(
    payload: AgentCreate,
    session: DatabaseSession,
) -> None:
    model = await session.get(ProviderModel, payload.chat_model_id)
    if model is None or model.kind != "chat" or not model.is_enabled:
        raise HTTPException(status_code=422, detail="Chat 模型不存在或不可用")
    requested_kbs = set(payload.knowledge_base_ids)
    actual_kbs = set(
        (
            await session.scalars(
                select(KnowledgeBase.id).where(KnowledgeBase.id.in_(requested_kbs))
            )
        ).all()
    )
    if actual_kbs != requested_kbs:
        raise HTTPException(status_code=422, detail="Agent 包含不存在的知识库")
    requested_users = set(payload.user_ids)
    if requested_users:
        actual_users = set(
            (
                await session.scalars(
                    select(User.id).where(
                        User.id.in_(requested_users),
                        User.is_active.is_(True),
                    )
                )
            ).all()
        )
        if actual_users != requested_users:
            raise HTTPException(status_code=422, detail="Agent 包含不存在或已停用的用户")


def _access_clause(user: CurrentUser) -> ColumnElement[bool]:
    if user.role == "admin":
        return true()
    return and_(
        Agent.is_enabled.is_(True),
        or_(
            Agent.visibility == "all",
            exists(
                select(agent_users.c.user_id).where(
                    agent_users.c.agent_id == Agent.id,
                    agent_users.c.user_id == user.id,
                )
            ),
        ),
    )


async def _get_accessible_agent(
    session: DatabaseSession,
    user: CurrentUser,
    agent_id: uuid.UUID,
) -> Agent:
    agent = await session.scalar(select(Agent).where(Agent.id == agent_id, _access_clause(user)))
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在或无权访问")
    return agent


@router.get("", response_model=list[AgentRead])
async def list_agents(user: CurrentUser, session: DatabaseSession) -> list[Agent]:
    return list(
        (
            await session.scalars(
                select(Agent).where(_access_clause(user)).order_by(Agent.updated_at.desc())
            )
        ).all()
    )


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> Agent:
    require_admin(user)
    await _validate_agent_config(payload, session)
    agent = Agent(
        name=payload.name,
        avatar=payload.avatar,
        description=payload.description,
        system_prompt=payload.system_prompt,
        chat_model_id=payload.chat_model_id,
        visibility=payload.visibility,
        max_steps=payload.max_steps,
        max_tokens=payload.max_tokens,
        timeout_seconds=payload.timeout_seconds,
        recommended_questions=payload.recommended_questions,
        created_by_id=user.id,
    )
    session.add(agent)
    await session.flush()
    await session.execute(
        agent_knowledge_bases.insert(),
        [
            {"agent_id": agent.id, "knowledge_base_id": knowledge_base_id}
            for knowledge_base_id in set(payload.knowledge_base_ids)
        ],
    )
    if payload.user_ids:
        await session.execute(
            agent_users.insert(),
            [{"agent_id": agent.id, "user_id": user_id} for user_id in set(payload.user_ids)],
        )
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="agent.create",
            resource_type="agent",
            resource_id=agent.id,
            metadata_json={
                "visibility": agent.visibility,
                "knowledge_base_count": len(set(payload.knowledge_base_ids)),
            },
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return agent


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent_runtime(
    agent_id: uuid.UUID,
    payload: AgentRuntimeUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> Agent:
    require_admin(user)
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    model = await session.get(ProviderModel, payload.chat_model_id)
    if model is None or model.kind != "chat" or not model.is_enabled:
        raise HTTPException(status_code=422, detail="Agent Chat 模型不存在或不可用")
    agent.chat_model_id = payload.chat_model_id
    agent.max_steps = payload.max_steps
    agent.max_tokens = payload.max_tokens
    agent.timeout_seconds = payload.timeout_seconds
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="agent.runtime.update",
            resource_type="agent",
            resource_id=agent.id,
            metadata_json={
                "chat_model_id": str(payload.chat_model_id),
                "max_steps": payload.max_steps,
                "max_tokens": payload.max_tokens,
                "timeout_seconds": payload.timeout_seconds,
            },
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    await session.refresh(agent)
    return agent


@router.post(
    "/{agent_id}/runs",
    response_model=AgentRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_agent_run(
    agent_id: uuid.UUID,
    payload: AgentRunCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> AgentRun:
    await _get_accessible_agent(session, user, agent_id)
    if payload.session_id is not None:
        owned_session = await session.scalar(
            select(ChatSession.id).where(
                ChatSession.id == payload.session_id,
                ChatSession.user_id == user.id,
            )
        )
        if owned_session is None:
            raise HTTPException(status_code=404, detail="对话不存在")
    run = AgentRun(
        agent_id=agent_id,
        user_id=user.id,
        session_id=payload.session_id,
        status="queued",
        query=payload.query,
    )
    session.add(run)
    await session.commit()
    execute_agent_run.send(str(run.id))
    return run


@router.get("/{agent_id}/runs", response_model=AgentRunHistoryRead)
async def list_agent_runs(
    agent_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AgentRunHistoryRead:
    """List the current user's runs without loading full answers or citations."""

    await _get_accessible_agent(session, user, agent_id)
    filters = (
        AgentRun.agent_id == agent_id,
        AgentRun.user_id == user.id,
    )
    total = int(
        await session.scalar(
            select(func.count()).select_from(AgentRun).where(*filters)
        )
        or 0
    )
    rows = (
        await session.execute(
            select(
                AgentRun.id,
                AgentRun.agent_id,
                AgentRun.status,
                AgentRun.query,
                AgentRun.error_summary,
                AgentRun.started_at,
                AgentRun.finished_at,
                AgentRun.created_at,
                AgentRun.updated_at,
            )
            .where(*filters)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).mappings()
    return AgentRunHistoryRead(
        items=[AgentRunSummaryRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def _get_run(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> AgentRun:
    clauses = [AgentRun.id == run_id]
    if user.role != "admin":
        clauses.append(AgentRun.user_id == user.id)
    run = await session.scalar(select(AgentRun).where(*clauses))
    if run is None:
        raise HTTPException(status_code=404, detail="Agent 运行不存在")
    return run


@router.get("/runs/{run_id}", response_model=AgentRunRead)
async def get_agent_run(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> AgentRun:
    return await _get_run(run_id, user, session)


@router.post("/runs/{run_id}/cancel", response_model=AgentRunRead)
async def cancel_agent_run(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> AgentRun:
    run = await _get_run(run_id, user, session)
    if run.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="运行已结束，无法取消")
    run.cancel_requested_at = datetime.now(UTC)
    await session.commit()
    return run


@router.get("/runs/{run_id}/steps")
async def get_agent_steps(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> list[dict[str, object]]:
    await _get_run(run_id, user, session)
    steps = (
        await session.scalars(
            select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.ordinal)
        )
    ).all()
    return [
        {
            "ordinal": step.ordinal,
            "kind": step.kind,
            "status": step.status,
            "summary": step.summary,
            "tool_name": step.tool_name,
            "input": step.input_json,
            "output_summary": step.output_summary,
            "duration_ms": step.duration_ms,
        }
        for step in steps
    ]


@router.get("/runs/{run_id}/events")
async def agent_run_events(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    await _get_run(run_id, user, session)
    stream_key = f"agent:run:{run_id}"
    start_id = last_event_id or "0-0"

    async def events() -> AsyncIterator[str]:
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        cursor = start_id
        try:
            while True:
                records = await redis.xread({stream_key: cursor}, block=15_000, count=100)
                if not records:
                    yield ": heartbeat\n\n"
                    continue
                for _, entries in records:
                    for event_id, fields in entries:
                        cursor = event_id
                        event = fields["event"]
                        data = json.loads(fields["data"])
                        yield (
                            f"id: {event_id}\n"
                            f"event: {event}\n"
                            f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                        )
                        if event in {"run.completed", "run.cancelled", "run.error"}:
                            return
                await asyncio.sleep(0)
        finally:
            await redis.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
