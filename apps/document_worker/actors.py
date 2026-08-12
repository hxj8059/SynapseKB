from __future__ import annotations

import asyncio
import uuid

import dramatiq
from synapsekb.document_processing.pipeline import process_document_job
from synapsekb.tasks.broker import broker

dramatiq.set_broker(broker)


@dramatiq.actor(
    queue_name="document",
    max_retries=3,
    min_backoff=5_000,
    max_backoff=60_000,
    time_limit=1_800_000,
)
def process_document(job_id: str) -> None:
    result = asyncio.run(process_document_job(uuid.UUID(job_id)))
    if result == "waiting_ocr":
        from apps.ocr_worker.actors import process_ocr

        process_ocr.send(job_id)
