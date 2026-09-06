from __future__ import annotations

import asyncio
import uuid

import dramatiq
from synapsekb.document_processing.pipeline import process_document_job
from synapsekb.tasks.broker import broker
from synapsekb.tasks.dispatch import run_dispatched

dramatiq.set_broker(broker)


@dramatiq.actor(
    queue_name="document",
    max_retries=3,
    min_backoff=5_000,
    max_backoff=60_000,
    time_limit=1_800_000,
)
def process_document(job_id: str) -> None:
    parsed_id = uuid.UUID(job_id)
    asyncio.run(run_dispatched("document", parsed_id, lambda: process_document_job(parsed_id)))
