from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    content: bytes
    media_type: str
    suffix: str
    final_url: str


def _validate_url_shape(url: str, allowed_ports: set[int]) -> tuple[str, int]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("网页 URL 只支持 HTTP 或 HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("网页 URL 主机无效或包含凭据")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in allowed_ports:
        raise ValueError("网页 URL 端口不在允许列表")
    return parsed.hostname, port


def _require_public_address(address: str) -> None:
    ip = ipaddress.ip_address(address)
    if not ip.is_global:
        raise ValueError("网页 URL 解析到内网、回环或保留地址")


async def validate_public_url(url: str, allowed_ports: set[int]) -> None:
    """Resolve every target before requesting it to prevent common SSRF paths."""

    hostname, port = _validate_url_shape(url, allowed_ports)
    try:
        _require_public_address(hostname.strip("[]"))
        return
    except ValueError as exc:
        if "does not appear" not in str(exc):
            raise
    loop = asyncio.get_running_loop()
    try:
        records = await loop.getaddrinfo(
            hostname.encode("idna").decode(),
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("网页 URL 域名无法解析") from exc
    addresses = {record[4][0] for record in records}
    if not addresses:
        raise ValueError("网页 URL 域名没有可用地址")
    for address in addresses:
        _require_public_address(address)


async def fetch_public_document(
    url: str,
    *,
    allowed_ports: set[int],
    max_bytes: int,
    max_redirects: int = 5,
) -> FetchedDocument:
    current = url
    headers = {"User-Agent": "SynapseKB-DocumentFetcher/0.1"}
    timeout = httpx.Timeout(20, connect=8)
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout,
        trust_env=False,
        headers=headers,
    ) as client:
        for redirect_count in range(max_redirects + 1):
            await validate_public_url(current, allowed_ports)
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    if redirect_count == max_redirects:
                        raise ValueError("网页 URL 重定向次数过多")
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("网页 URL 返回无目标重定向")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                raw_media_type = response.headers.get("content-type", "")
                media_type = raw_media_type.split(";", 1)[0].strip().lower()
                supported = {
                    "text/html": ".html",
                    "application/xhtml+xml": ".html",
                    "text/plain": ".txt",
                    "text/markdown": ".md",
                    "application/pdf": ".pdf",
                }
                if media_type not in supported:
                    raise ValueError(f"网页 URL 内容类型不受支持: {media_type or '未知'}")
                declared_length = response.headers.get("content-length")
                if declared_length and int(declared_length) > max_bytes:
                    raise ValueError("网页 URL 内容超过大小限制")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise ValueError("网页 URL 内容超过大小限制")
                if not content:
                    raise ValueError("网页 URL 返回空内容")
                if media_type == "application/pdf" and not content.startswith(b"%PDF-"):
                    raise ValueError("网页 URL 声明为 PDF，但内容签名无效")
                return FetchedDocument(
                    content=bytes(content),
                    media_type=media_type,
                    suffix=supported[media_type],
                    final_url=str(response.url),
                )
    raise RuntimeError("网页抓取未返回结果")
