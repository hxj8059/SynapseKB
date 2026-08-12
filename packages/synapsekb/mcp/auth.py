from __future__ import annotations

import contextvars
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from starlette.types import ASGIApp, Receive, Scope, Send

from synapsekb.auth.security import hash_token
from synapsekb.config import get_settings
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


async def _json_response(send: Send, status: int, message: str) -> None:
    body = json.dumps({"error": message}, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class McpSecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.settings = get_settings()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        origin = headers.get("origin")
        if origin and origin not in self.settings.mcp_allowed_origins:
            await _json_response(send, 403, "Origin 不被允许")
            return
        authorization = headers.get("authorization", "")
        if not authorization.lower().startswith("bearer "):
            await _json_response(send, 401, "缺少 Bearer Token")
            return
        principal = await authenticate_pat(authorization.split(" ", 1)[1])
        if principal is None:
            await _json_response(send, 401, "Token 无效、已过期或已撤销")
            return
        redis = Redis.from_url(self.settings.redis_url, decode_responses=True)
        try:
            window = int(datetime.now(UTC).timestamp() // 60)
            key = f"rate:mcp:{principal.token_id}:{window}"
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 70)
            if count > self.settings.mcp_rate_limit_per_minute:
                await _json_response(send, 429, "请求过于频繁")
                return
        finally:
            await redis.aclose()
        token = principal_var.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            principal_var.reset(token)
