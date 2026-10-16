import asyncio
import json
import uuid
from datetime import UTC, datetime

import dramatiq
from redis.asyncio import Redis
from synapsekb.agent.engine import run_agent
from synapsekb.config import get_settings
from synapsekb.database.models import AgentRun
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.tasks.broker import broker
from synapsekb.tasks.dispatch import run_dispatched

dramatiq.set_broker(broker)

MAX_AGENT_RETRIES = 2


@dramatiq.actor(
    queue_name="agent",
    max_retries=MAX_AGENT_RETRIES,
    min_backoff=10_000,
    max_backoff=60_000,
    time_limit=960_000,
)
def execute_agent_run(run_id: str) -> None:
    parsed_id = uuid.UUID(run_id)

    async def report_error(exc: Exception, retry: bool, attempt: int) -> None:
        if retry:
            await _mark_agent_retrying(parsed_id, exc, attempt)
        else:
            await _mark_agent_failed(parsed_id, exc)

    asyncio.run(
        run_dispatched(
            "agent",
            parsed_id,
            lambda: run_agent(parsed_id),
            on_error=report_error,
        )
    )


async def _mark_agent_retrying(run_id: uuid.UUID, exc: Exception, attempt: int) -> None:
    summary = f"{type(exc).__name__}: {exc}"[:700]
    async with AsyncSessionFactory() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status in {"completed", "cancelled"}:
            return
        run.status = "queued"
        run.error_summary = None
        run.finished_at = None
        await session.commit()
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await redis.xadd(
            f"agent:run:{run_id}",
            {
                "event": "thinking.summary",
                "data": json.dumps(
                    {
                        "summary": (
                            f"本次执行遇到可恢复错误，正在自动恢复（{attempt}/{MAX_AGENT_RETRIES}）："
                            f"{summary}"
                        )
                    },
                    ensure_ascii=False,
                ),
            },
            maxlen=1000,
            approximate=True,
        )
    finally:
        await redis.aclose()


async def _mark_agent_failed(run_id: uuid.UUID, exc: Exception) -> None:
    summary = f"{type(exc).__name__}: {exc}"[:1000]
    async with AsyncSessionFactory() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status in {"completed", "cancelled"}:
            return
        run.status = "failed"
        run.error_summary = summary
        run.finished_at = datetime.now(UTC)
        await session.commit()
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await redis.xadd(
            f"agent:run:{run_id}",
            {
                "event": "run.error",
                "data": json.dumps({"message": summary}, ensure_ascii=False),
            },
            maxlen=1000,
            approximate=True,
        )
    finally:
        await redis.aclose()
