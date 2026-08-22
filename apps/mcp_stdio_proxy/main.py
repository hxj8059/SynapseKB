from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, Tool

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _read_boolean_env(name: str) -> bool:
    value = os.environ.get(name, "").strip().casefold()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise RuntimeError(f"{name} 必须是 true/false、1/0、yes/no 或 on/off")


def resolve_remote_mcp_url(base_url: str, *, allow_insecure_http: bool) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("SYNAPSEKB_URL 必须是完整的 HTTP(S) 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("SYNAPSEKB_URL 不能包含凭据、Query 或 Fragment")
    if parsed.path not in {"", "/", "/mcp"}:
        raise RuntimeError("SYNAPSEKB_URL 只能填写服务根地址或 /mcp 地址")
    if (
        parsed.scheme == "http"
        and parsed.hostname not in _LOOPBACK_HOSTS
        and not allow_insecure_http
    ):
        raise RuntimeError(
            "远程 HTTP 会明文传输 Bearer Token；确认接受风险后设置 "
            "SYNAPSEKB_ALLOW_INSECURE_HTTP=true"
        )
    return urlunsplit((parsed.scheme, parsed.netloc, "/mcp", "", ""))


@asynccontextmanager
async def remote_session(_server: Server[ClientSession]) -> AsyncIterator[ClientSession]:
    base_url = os.environ.get("SYNAPSEKB_URL", "").rstrip("/")
    token = os.environ.get("SYNAPSEKB_TOKEN", "")
    if not base_url or not token:
        raise RuntimeError("必须设置 SYNAPSEKB_URL 和 SYNAPSEKB_TOKEN")
    remote_mcp_url = resolve_remote_mcp_url(
        base_url,
        allow_insecure_http=_read_boolean_env("SYNAPSEKB_ALLOW_INSECURE_HTTP"),
    )
    async with (
        httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(30, read=310),
        ) as client,
        streamable_http_client(
            remote_mcp_url,
            http_client=client,
        ) as (read_stream, write_stream, _),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        yield session


server: Server[ClientSession] = Server(
    "synapsekb-mcp-proxy",
    version="0.1.0",
    lifespan=remote_session,
)


@server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
async def list_tools() -> list[Tool]:
    remote: ClientSession = server.request_context.lifespan_context
    result = await remote.list_tools()
    return result.tools


@server.call_tool(validate_input=True)  # type: ignore[untyped-decorator]
async def call_tool(
    name: str,
    arguments: dict[str, Any] | None,
) -> CallToolResult:
    remote: ClientSession = server.request_context.lifespan_context
    return await remote.call_tool(name, arguments or {})


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="synapsekb-mcp-proxy",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
