from __future__ import annotations

import hashlib
import ipaddress
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from fastapi import Request, Response
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from redis.exceptions import RedisError
from starlette.responses import JSONResponse
from structlog.contextvars import bind_contextvars, clear_contextvars

logger = structlog.get_logger()
tracer = trace.get_tracer("synapsekb.api")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")


def _remote_identity(request: Request) -> str:
    remote = request.client.host if request.client else "unknown"
    if not request.app.state.settings.trust_proxy_headers:
        return remote
    forwarded = request.headers.get("x-real-ip")
    if not forwarded:
        return remote
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return remote


async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    clear_contextvars()
    supplied_request_id = request.headers.get("x-request-id", "")
    request_id = (
        supplied_request_id if _REQUEST_ID.fullmatch(supplied_request_id) else str(uuid.uuid4())
    )
    request.state.request_id = request_id
    bind_contextvars(request_id=request_id, method=request.method, path=request.url.path)
    try:
        if request.url.path.startswith("/api/v1/") and not request.url.path.endswith("/health"):
            settings = request.app.state.settings
            authorization = request.headers.get("authorization", "")
            remote = _remote_identity(request)
            request.state.remote_ip = remote
            identity = (
                hashlib.sha256(authorization.encode()).hexdigest()[:24] if authorization else remote
            )
            auth_path = request.url.path in {
                "/api/v1/auth/login",
                "/api/v1/auth/refresh",
            }
            limit = (
                settings.auth_rate_limit_per_minute
                if auth_path
                else settings.api_rate_limit_per_minute
            )
            window = int(datetime.now(UTC).timestamp() // 60)
            key = f"rate:api:{identity}:{'auth' if auth_path else 'all'}:{window}"
            try:
                count = await request.app.state.redis.incr(key)
                if count == 1:
                    await request.app.state.redis.expire(key, 70)
                if count > limit:
                    rate_response = JSONResponse(
                        {"error": {"code": "rate_limited", "message": "请求过于频繁"}},
                        status_code=429,
                        headers={"Retry-After": "60"},
                    )
                    rate_response.headers["x-request-id"] = request_id
                    return rate_response
            except RedisError:
                logger.warning("api_rate_limit_unavailable")
        with tracer.start_as_current_span(f"{request.method} {request.url.path}") as span:
            response = await call_next(request)
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("url.path", request.url.path)
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 500:
                span.set_status(Status(StatusCode.ERROR))
        response.headers["x-request-id"] = request_id
        logger.info("http_request", status_code=response.status_code)
        return response
    finally:
        clear_contextvars()
