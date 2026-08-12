from __future__ import annotations

import asyncio
import os
import statistics
import time

import httpx
import pytest


@pytest.mark.load
async def test_retrieval_p95_against_seeded_environment() -> None:
    if os.getenv("RUN_LOAD_TESTS") != "1":
        pytest.skip("set RUN_LOAD_TESTS=1 against an explicitly seeded environment")
    base_url = os.environ["SYNAPSEKB_LOAD_URL"].rstrip("/")
    token = os.environ["SYNAPSEKB_LOAD_TOKEN"]
    knowledge_base_id = os.environ["SYNAPSEKB_LOAD_KB_ID"]
    requests = int(os.getenv("SYNAPSEKB_LOAD_REQUESTS", "100"))
    concurrency = int(os.getenv("SYNAPSEKB_LOAD_CONCURRENCY", "20"))
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []

    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    ) as client:

        async def run_once() -> None:
            async with semaphore:
                started = time.perf_counter()
                response = await client.post(
                    "/api/v1/search",
                    json={
                        "query": "知识库检索性能基线",
                        "knowledge_base_ids": [knowledge_base_id],
                        "document_ids": [],
                        "tag_ids": [],
                        "top_k": 20,
                    },
                )
                response.raise_for_status()
                latencies.append((time.perf_counter() - started) * 1000)

        await asyncio.gather(*(run_once() for _ in range(requests)))

    p95 = statistics.quantiles(latencies, n=100, method="inclusive")[94]
    assert p95 < float(os.getenv("SYNAPSEKB_LOAD_P95_MS", "1000")), f"P95={p95:.1f}ms"
