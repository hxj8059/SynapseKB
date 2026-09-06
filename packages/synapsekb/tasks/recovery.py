"""One-off, online-safe queue upgrade: python -m synapsekb.tasks.recovery [--apply]."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert

from synapsekb.database.models import ProcessingJob, TaskDispatch
from synapsekb.database.session import AsyncSessionFactory
from synapsekb.tasks.broker import broker
from synapsekb.tasks.dispatch import TASKS, publish_pending

# Only remove an exact, queued duplicate while a matching keeper still exists.
# Fetched/in-flight deliveries have no list entry and are left for worker fencing.
# Save the redundant payload before removal, atomically, for upgrade diagnostics.
DEDUPLICATE = """
if redis.call('hget', KEYS[2], ARGV[1]) ~= ARGV[3] then return 0 end
if not redis.call('hget', KEYS[3], ARGV[2]) then return 0 end
if not redis.call('lpos', KEYS[1], ARGV[1]) then return 0 end
for i = 5, #KEYS do
  if redis.call('sismember', KEYS[i], ARGV[1]) == 1 then return 0 end
end
redis.call('hset', KEYS[4], KEYS[2] .. ':' .. ARGV[1], ARGV[3])
redis.call('expire', KEYS[4], 604800)
redis.call('lrem', KEYS[1], 0, ARGV[1])
redis.call('hdel', KEYS[2], ARGV[1])
return 1
"""


def inventory() -> dict[tuple[str, uuid.UUID], list[dict[str, Any]]]:
    """Read message hashes (includes prefetch and delayed messages), not only LLEN."""
    result: dict[tuple[str, uuid.UUID], list[dict[str, Any]]] = {}
    actors = {actor for _, actor, _, _ in TASKS.values()}
    for queue in sorted({queue for queue, _, _, _ in TASKS.values()}):
        for name in (queue, f"{queue}.DQ"):
            key = f"{broker.namespace}:{name}"
            for message_id, raw in broker.client.hscan_iter(f"{key}.msgs", count=500):
                try:
                    message = json.loads(raw)
                    actor = message["actor_name"]
                    if actor not in actors:
                        continue
                    task_id = uuid.UUID(message["args"][0])
                    mid = message_id.decode() if isinstance(message_id, bytes) else message_id
                    item = {
                        "key": key,
                        "id": mid,
                        "raw": raw,
                        "inflight": broker.client.lpos(key, mid) is None,
                    }
                    result.setdefault((actor, task_id), []).append(item)
                except (ValueError, KeyError, IndexError, TypeError):
                    continue  # Unknown payloads are never removed.
    return result


def deduplicate_messages(*, apply: bool) -> dict[str, Any]:
    messages = inventory()
    backup = f"{broker.namespace}:dispatch-upgrade-backup:{uuid.uuid4()}"
    candidates = removed = 0
    for group in messages.values():
        group.sort(key=lambda item: not item["inflight"])
        keeper = group[0]
        for item in group[1:]:
            if item["inflight"]:
                continue
            candidates += 1
            if apply:
                ack_keys = list(broker.client.scan_iter(f"{broker.namespace}:__acks__.*"))
                keys = [
                    item["key"],
                    f"{item['key']}.msgs",
                    f"{keeper['key']}.msgs",
                    backup,
                    *ack_keys,
                ]
                removed += cast(
                    int,
                    broker.client.eval(
                        DEDUPLICATE, len(keys), *keys, item["id"], keeper["id"], item["raw"]
                    ),
                )
    return {
        "business_tasks": len(messages),
        "queued_duplicates": candidates,
        "removed": removed,
        "backup_key": backup if removed else None,
    }


async def backfill_dispatches(*, apply: bool) -> int:
    """Adopt existing messages; only missing deliveries become pending."""
    messages = await asyncio.to_thread(inventory)
    count = 0
    for task_type, (queue, actor, model, _) in TASKS.items():
        if task_type == "document_resume":
            continue  # ProcessingJob's phase chooses its dispatch type below.
        cursor: uuid.UUID | None = None
        while True:
            async with AsyncSessionFactory() as session:
                query = select(model).where(
                    model.status.in_({"queued", "running", "quality_check", "waiting_tasks"})
                )
                if model is ProcessingJob:
                    query = query.where(
                        model.stage.in_({"waiting_ocr", "ocr"})
                        if task_type == "ocr"
                        else model.stage.not_in({"waiting_ocr", "ocr"})
                    )
                if cursor:
                    query = query.where(model.id > cursor)
                rows = (await session.scalars(query.order_by(model.id).limit(500))).all()
                if not rows:
                    break
                for job in rows:
                    phase = (
                        "document_resume"
                        if task_type == "document" and job.stage == "ocr_completed"
                        else task_type
                    )
                    already = await session.scalar(
                        select(
                            exists().where(
                                TaskDispatch.task_type == phase, TaskDispatch.task_id == job.id
                            )
                        )
                    )
                    if already:
                        continue
                    count += 1
                    if not apply:
                        continue
                    group = messages.get((actor, job.id), [])
                    # Prefer a fetched message so live processing remains represented.
                    group.sort(key=lambda item: not item["inflight"])
                    current = group[0] if group else None
                    running = job.status != "queued"
                    now = datetime.now(UTC)
                    await session.execute(
                        insert(TaskDispatch)
                        .values(
                            id=uuid.uuid4(),
                            task_type=phase,
                            task_id=job.id,
                            queue_name=queue,
                            actor_name=actor,
                            redis_message_id=current["id"] if current else str(uuid.uuid4()),
                            status="claimed" if running else "sent" if current else "pending",
                            attempts=0,
                            available_at=now,
                            sent_at=now if current else None,
                            heartbeat_at=now if running else None,
                        )
                        .on_conflict_do_nothing(constraint="uq_task_dispatch_identity")
                    )
                cursor = rows[-1].id
                await session.commit()
    return count


async def upgrade_queues(*, apply: bool) -> dict[str, Any]:
    result = await asyncio.to_thread(deduplicate_messages, apply=apply)
    result["dispatches_backfilled"] = await backfill_dispatches(apply=apply)
    result["published"] = await publish_pending(limit=1000) if apply else 0
    result["mode"] = "apply" if apply else "dry_run"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="审计并修复历史重复投递，默认只读")
    parser.add_argument("--apply", action="store_true", help="原子去重并补投确实丢失的消息")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(upgrade_queues(apply=args.apply)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
