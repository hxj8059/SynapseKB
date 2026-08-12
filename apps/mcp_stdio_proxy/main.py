from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, Tool


@asynccontextmanager
async def remote_session(_server: Server[ClientSession]) -> AsyncIterator[ClientSession]:
    base_url = os.environ.get("SYNAPSEKB_URL", "").rstrip("/")
    token = os.environ.get("SYNAPSEKB_TOKEN", "")
    if not base_url or not token:
        raise RuntimeError("必须设置 SYNAPSEKB_URL 和 SYNAPSEKB_TOKEN")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("远程 SynapseKB 必须使用 HTTPS")
    async with (
        httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(30, read=310),
        ) as client,
        streamable_http_client(
            f"{base_url}/mcp",
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
