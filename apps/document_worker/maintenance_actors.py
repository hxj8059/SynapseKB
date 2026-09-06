from __future__ import annotations

import asyncio
import uuid

import dramatiq
from synapsekb.knowledge_bases.deletion import (
    mark_knowledge_base_deletion_failed,
    run_knowledge_base_deletion,
)
from synapsekb.tasks.broker import broker
from synapsekb.tasks.dispatch import run_dispatched

dramatiq.set_broker(broker)


@dramatiq.actor(
    queue_name="maintenance",
    max_retries=5,
    min_backoff=10_000,
    max_backoff=60_000,
    time_limit=10_800_000,
)
def delete_knowledge_base(job_id: str) -> None:
    parsed_id = uuid.UUID(job_id)

    async def work() -> str:
        try:
            return await run_knowledge_base_deletion(parsed_id)
        except Exception as exc:
            await mark_knowledge_base_deletion_failed(parsed_id, exc)
            raise

    asyncio.run(run_dispatched("kb_delete", parsed_id, work))
