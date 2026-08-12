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

dramatiq.set_broker(broker)


@dramatiq.actor(
    queue_name="agent",
    max_retries=2,
    min_backoff=10_000,
    max_backoff=60_000,
    time_limit=360_000,
)
def execute_agent_run(run_id: str) -> None:
    parsed_id = uuid.UUID(run_id)
    try:
        asyncio.run(run_agent(parsed_id))
    except Exception as exc:
        asyncio.run(_mark_agent_failed(parsed_id, exc))
        raise


async def _mark_agent_failed(run_id: uuid.UUID, exc: Exception) -> None:
    summary = f"{type(exc).__name__}: {exc}"[:1000]
    async with AsyncSessionFactory() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status in {"completed", "cancelled", "failed"}:
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
