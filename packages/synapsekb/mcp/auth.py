from __future__ import annotations

import contextvars
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from synapsekb.auth.security import hash_token
from synapsekb.config import Settings, get_settings
from synapsekb.database.models import PersonalAccessToken, User
from synapsekb.database.session import AsyncSessionFactory


@dataclass(frozen=True, slots=True)
class McpPrincipal:
    user_id: uuid.UUID
    token_id: uuid.UUID
    scopes: frozenset[str]


principal_var: contextvars.ContextVar[McpPrincipal | None] = contextvars.ContextVar(
    "synapsekb_mcp_principal",
    default=None,
)


async def authenticate_pat(raw_token: str) -> McpPrincipal | None:
    now = datetime.now(UTC)
    async with AsyncSessionFactory() as session:
        token = await session.scalar(
            select(PersonalAccessToken).where(
                PersonalAccessToken.token_hash == hash_token(raw_token),
                PersonalAccessToken.revoked_at.is_(None),
            )
        )
        if token is None or (token.expires_at is not None and token.expires_at <= now):
            return None
        user = await session.get(User, token.user_id)
        if user is None or not user.is_active:
            return None
        if token.last_used_at is None or (now - token.last_used_at).total_seconds() >= 300:
            token.last_used_at = now
            await session.commit()
        return McpPrincipal(user.id, token.id, frozenset(token.scopes))


def _matches_allowlist(value: str, allowed_values: list[str]) -> bool:
    if value in allowed_values:
        return True
    return any(
        allowed.endswith(":*") and value.startswith(f"{allowed[:-2]}:")
        for allowed in allowed_values
    )


def _cors_headers(origin: str | None) -> list[tuple[bytes, bytes]]:
    if not origin:
        return []
    return [
        (b"access-control-allow-origin", origin.encode("latin-1")),
        (b"access-control-allow-credentials", b"true"),
        (b"access-control-expose-headers", b"Mcp-Session-Id, MCP-Protocol-Version"),
        (b"vary", b"Origin"),
    ]


async def _json_response(
    send: Send,
    status: int,
    message: str,
    *,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps({"error": message}, ensure_ascii=False).encode()
    response_headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode()),
        *(extra_headers or []),
    ]
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": response_headers,
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _preflight_response(send: Send, origin: str) -> None:
    headers = [
        *_cors_headers(origin),
        (b"access-control-allow-methods", b"GET, POST, DELETE, OPTIONS"),
        (
            b"access-control-allow-headers",
            b"Authorization, Content-Type, Accept, Mcp-Session-Id, "
            b"MCP-Protocol-Version, Last-Event-ID",
        ),
        (b"access-control-max-age", b"600"),
        (b"content-length", b"0"),
    ]
    await send({"type": "http.response.start", "status": 204, "headers": headers})
    await send({"type": "http.response.body", "body": b""})


class McpSecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings | None = None) -> None:
        self.app = app
        self.settings = settings or get_settings()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        origin = headers.get("origin")
        allowed_origins = self.settings.mcp_transport_allowed_origins
        if origin and not _matches_allowlist(origin, allowed_origins):
            await _json_response(send, 403, "Origin 不被允许")
            return
        cors_headers = _cors_headers(origin)
        if scope.get("method", "").upper() == "OPTIONS":
            if not origin:
                await _json_response(send, 400, "CORS 预检缺少 Origin")
                return
            requested_method = headers.get("access-control-request-method", "POST").upper()
            if requested_method not in {"GET", "POST", "DELETE"}:
                await _json_response(
                    send,
                    405,
                    "CORS 预检方法不被允许",
                    extra_headers=cors_headers,
                )
                return
            await _preflight_response(send, origin)
            return
        authorization = headers.get("authorization", "")
        if not authorization.lower().startswith("bearer "):
            await _json_response(send, 401, "缺少 Bearer Token", extra_headers=cors_headers)
            return
        principal = await authenticate_pat(authorization.split(" ", 1)[1])
        if principal is None:
            await _json_response(
                send,
                401,
                "Token 无效、已过期或已撤销",
                extra_headers=cors_headers,
            )
            return
        redis = Redis.from_url(self.settings.redis_url, decode_responses=True)
        try:
            window = int(datetime.now(UTC).timestamp() // 60)
            key = f"rate:mcp:{principal.token_id}:{window}"
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 70)
            if count > self.settings.mcp_rate_limit_per_minute:
                await _json_response(
                    send,
                    429,
                    "请求过于频繁",
                    extra_headers=cors_headers,
                )
                return
        finally:
            await redis.aclose()
        token = principal_var.set(principal)

        async def send_with_cors(message: Message) -> None:
            if cors_headers and message.get("type") == "http.response.start":
                message = dict(message)
                existing = list(message.get("headers", []))
                message["headers"] = [*existing, *cors_headers]
            await send(message)

        try:
            await self.app(scope, receive, send_with_cors)
        finally:
            principal_var.reset(token)
