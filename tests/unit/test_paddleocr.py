import httpx
import pytest
from synapsekb.document_processing.paddleocr import (
    OcrCancelled,
    PaddleOcrCloudClient,
)


async def test_paddleocr_wait_converts_official_api_result() -> None:
    async def api_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/ocr/jobs/task-1"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "state": "done",
                    "resultUrl": {"jsonUrl": "https://result.example/result.jsonl"},
                },
            },
        )

    async def result_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "result.example"
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            text="\n".join(
                [
                    '{"result":{"layoutParsingResults":[{"markdown":{"text":"# 第一页"}}]}}',
                    '{"result":{"layoutParsingResults":[{"markdown":{"text":"第二页"}}]}}',
                ]
            ),
        )

    client = PaddleOcrCloudClient(
        base_url="https://ocr.example",
        api_key="secret",
        poll_interval_seconds=0,
    )
    await client.client.aclose()
    await client.result_client.aclose()
    client.client = httpx.AsyncClient(
        base_url="https://ocr.example",
        headers={"Authorization": "Bearer secret"},
        transport=httpx.MockTransport(api_handler),
    )
    client.result_client = httpx.AsyncClient(transport=httpx.MockTransport(result_handler))
    try:
        result = await client.wait("task-1", model="PaddleOCR-VL-1.6")
    finally:
        await client.close()
    assert result.markdown == "<!-- page:1 -->\n# 第一页\n\n<!-- page:2 -->\n第二页"
    assert result.page_count == 2
    assert result.metadata["service"] == "paddleocr-official-api"


async def test_paddleocr_wait_honors_cancellation_before_polling() -> None:
    client = PaddleOcrCloudClient(base_url=None, api_key="secret")

    async def cancelled() -> bool:
        return True

    try:
        with pytest.raises(OcrCancelled):
            await client.wait(
                "task-1",
                model="PaddleOCR-VL-1.6",
                is_cancelled=cancelled,
            )
    finally:
        await client.close()


async def test_paddleocr_parses_pp_ocr_v6_text() -> None:
    async def api_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "state": "done",
                    "resultUrl": {"jsonUrl": "https://result.example/result.jsonl"},
                },
            },
        )

    async def result_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='{"result":{"ocrResults":[{"prunedResult":{"rec_texts":["第一行","第二行"]}}]}}',
        )

    client = PaddleOcrCloudClient(
        base_url="https://ocr.example",
        api_key="secret",
        poll_interval_seconds=0,
    )
    await client.client.aclose()
    await client.result_client.aclose()
    client.client = httpx.AsyncClient(
        base_url="https://ocr.example",
        transport=httpx.MockTransport(api_handler),
    )
    client.result_client = httpx.AsyncClient(transport=httpx.MockTransport(result_handler))
    try:
        result = await client.wait("task-1", model="PP-OCRv6")
    finally:
        await client.close()
    assert "第一行\n第二行" in result.markdown
