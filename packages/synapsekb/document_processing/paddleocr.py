from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

DEFAULT_PADDLEOCR_BASE_URL = "https://paddleocr.aistudio-app.com"
PADDLEOCR_JOBS_PATH = "/api/v2/ocr/jobs"
DOCUMENT_PARSING_MODELS = {"PaddleOCR-VL-1.6", "PP-StructureV3"}


@dataclass(frozen=True, slots=True)
class OcrResult:
    task_id: str
    markdown: str
    page_count: int
    metadata: dict[str, Any]


class OcrCancelled(RuntimeError):
    pass


class OcrTransientError(RuntimeError):
    pass


class PaddleOcrCloudClient:
    """Lightweight adapter for PaddleOCR's official asynchronous cloud API."""

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str,
        timeout_seconds: int = 60,
        poll_interval_seconds: float = 2,
    ) -> None:
        if not api_key:
            raise ValueError("PaddleOCR Access Token 未配置")
        self.client = httpx.AsyncClient(
            base_url=(base_url or DEFAULT_PADDLEOCR_BASE_URL).rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Client-Platform": "SynapseKB",
            },
            timeout=timeout_seconds,
            trust_env=False,
        )
        # Result URLs may be signed object-storage links. Never forward the API token.
        self.result_client = httpx.AsyncClient(timeout=timeout_seconds, trust_env=False)
        self.poll_interval_seconds = poll_interval_seconds

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.NetworkError, OcrTransientError)
        ),
        reraise=True,
    )
    async def submit(self, path: Path, *, model: str) -> str:
        _validate_model(model)
        with path.open("rb") as handle:
            response = await self.client.post(
                PADDLEOCR_JOBS_PATH,
                data={"model": model, "optionalPayload": "{}"},
                files={"file": (path.name, handle, "application/octet-stream")},
            )
        data = _api_data(response)
        task_id = data.get("jobId")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("PaddleOCR 响应缺少 jobId")
        return task_id

    async def wait(
        self,
        task_id: str,
        *,
        model: str,
        timeout_seconds: int = 600,
        is_cancelled: Callable[[], Awaitable[bool]] | None = None,
    ) -> OcrResult:
        _validate_model(model)
        started = time.perf_counter()
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            if is_cancelled is not None and await is_cancelled():
                raise OcrCancelled("OCR 任务已取消")
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"OCR task {task_id} timed out")
            status = await self._get_status(task_id)
            state = status.get("state")
            if state == "done":
                pages = await self._fetch_result_pages(status, model=model)
                markdown = "\n\n".join(
                    f"<!-- page:{number} -->\n{text.strip()}"
                    for number, text in enumerate(pages, start=1)
                    if text.strip()
                )
                return OcrResult(
                    task_id=task_id,
                    markdown=markdown,
                    page_count=len(pages),
                    metadata={
                        "model": model,
                        "service": "paddleocr-official-api",
                        "duration_ms": round((time.perf_counter() - started) * 1000),
                    },
                )
            if state == "failed":
                summary = str(status.get("errorMsg") or "PaddleOCR 云任务失败")
                raise RuntimeError(summary[:1000])
            if state not in {"pending", "running"}:
                raise RuntimeError(f"PaddleOCR 返回未知任务状态: {state}")
            await asyncio.sleep(self.poll_interval_seconds)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.NetworkError, OcrTransientError)
        ),
        reraise=True,
    )
    async def _get_status(self, task_id: str) -> dict[str, Any]:
        return _api_data(await self.client.get(f"{PADDLEOCR_JOBS_PATH}/{task_id}"))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.NetworkError, OcrTransientError)
        ),
        reraise=True,
    )
    async def _fetch_result_pages(self, status: dict[str, Any], *, model: str) -> list[str]:
        result_url = status.get("resultUrl")
        json_url = result_url.get("jsonUrl") if isinstance(result_url, dict) else None
        if not isinstance(json_url, str) or not json_url.startswith("https://"):
            raise RuntimeError("PaddleOCR 完成响应缺少安全的结果 URL")
        response = await self.result_client.get(json_url)
        _raise_for_retryable_status(response)
        response.raise_for_status()
        try:
            lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise RuntimeError("PaddleOCR 结果不是有效 JSONL") from exc
        return _parse_pages(lines, model=model)

    async def close(self) -> None:
        await self.client.aclose()
        await self.result_client.aclose()


def _validate_model(model: str) -> None:
    if model != "PP-OCRv6" and model not in DOCUMENT_PARSING_MODELS:
        raise ValueError(f"不支持的 PaddleOCR 模型: {model}")


def _raise_for_retryable_status(response: httpx.Response) -> None:
    if response.status_code in {429, 502, 503, 504}:
        raise OcrTransientError(f"PaddleOCR 暂时不可用: HTTP {response.status_code}")


def _api_data(response: httpx.Response) -> dict[str, Any]:
    _raise_for_retryable_status(response)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("PaddleOCR 响应不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("PaddleOCR 响应格式无效")
    if payload.get("code") not in {0, None}:
        summary = str(payload.get("msg") or payload.get("message") or "PaddleOCR API 错误")
        raise RuntimeError(summary[:1000])
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("PaddleOCR 响应缺少 data")
    return data


def _parse_pages(lines: list[Any], *, model: str) -> list[str]:
    pages: list[str] = []
    for line in lines:
        result = line.get("result") if isinstance(line, dict) else None
        if not isinstance(result, dict):
            raise RuntimeError("PaddleOCR 结果缺少 result")
        if model == "PP-OCRv6":
            entries = result.get("ocrResults")
            if not isinstance(entries, list):
                raise RuntimeError("PaddleOCR 结果缺少 ocrResults")
            pages.extend(
                _ocr_page_text(entry.get("prunedResult"))
                for entry in entries
                if isinstance(entry, dict)
            )
        else:
            entries = result.get("layoutParsingResults")
            if not isinstance(entries, list):
                raise RuntimeError("PaddleOCR 结果缺少 layoutParsingResults")
            for entry in entries:
                markdown = entry.get("markdown") if isinstance(entry, dict) else None
                text = markdown.get("text") if isinstance(markdown, dict) else None
                if not isinstance(text, str):
                    raise RuntimeError("PaddleOCR 页面缺少 Markdown")
                pages.append(text)
    return pages


def _ocr_page_text(value: Any) -> str:
    """Extract readable text from PP-OCRv6's deliberately flexible result JSON."""

    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (_ocr_page_text(item) for item in value)))
    if not isinstance(value, dict):
        return ""
    for key in ("rec_texts", "recTexts", "texts"):
        texts = value.get(key)
        if isinstance(texts, list):
            return "\n".join(str(text) for text in texts if str(text).strip())
    for key in ("text", "markdown"):
        text = value.get(key)
        if isinstance(text, str):
            return text
    return "\n".join(filter(None, (_ocr_page_text(item) for item in value.values())))
