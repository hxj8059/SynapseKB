from __future__ import annotations

import asyncio
import uuid

import dramatiq
from synapsekb.knowledge_bases.deletion import (
    mark_knowledge_base_deletion_failed,
    run_knowledge_base_deletion,
)
from synapsekb.tasks.broker import broker

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
    try:
        result = asyncio.run(run_knowledge_base_deletion(parsed_id))
        if result == "waiting":
            # Waiting for document/OCR/Wiki workers is an expected state rather
            # than a failure. Schedule a fresh message so a long-running source
            # task cannot exhaust Dramatiq's retry budget and strand the job.
            delete_knowledge_base.send_with_options(
                args=(job_id,),
                delay=15_000,
            )
    except Exception as exc:
        asyncio.run(mark_knowledge_base_deletion_failed(parsed_id, exc))
        raise
