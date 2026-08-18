import asyncio
import uuid

import dramatiq
from synapsekb.tasks.broker import broker
from synapsekb.wiki.generator import generate_wiki_job
from synapsekb.wiki.health import run_wiki_health_job

dramatiq.set_broker(broker)


@dramatiq.actor(
    queue_name="wiki",
    # The generator performs schema-aware compact and small-batch recovery.
    # Retrying the whole document after it has been marked failed repeats every
    # expensive model call and makes a deterministic error look "stuck".
    max_retries=0,
    time_limit=3_600_000,
)
def generate_wiki(job_id: str) -> None:
    asyncio.run(generate_wiki_job(uuid.UUID(job_id)))


@dramatiq.actor(
    queue_name="wiki",
    max_retries=2,
    min_backoff=30_000,
    max_backoff=120_000,
    time_limit=1_800_000,
)
def check_wiki_health(job_id: str) -> None:
    asyncio.run(run_wiki_health_job(uuid.UUID(job_id)))
