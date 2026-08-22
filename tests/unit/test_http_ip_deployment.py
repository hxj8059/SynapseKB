from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import Response
from synapsekb.api.routes import auth as auth_routes
from synapsekb.config import Settings
from synapsekb.mcp.auth import McpSecurityMiddleware


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": "test",
        "public_base_url": "http://203.0.113.10:8088",
        "jwt_secret": "unit-test-secret-at-least-32-characters",
        "trusted_hosts": ["api", "mcp-server"],
        "cors_origins": [],
        "mcp_allowed_origins": [],
    }
    values.update(overrides)
    return Settings(**values)


async def _ok_app(scope: Any, receive: Any, send: Any) -> None:
    del scope, receive
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": b"{}"})


def test_public_ip_is_automatically_added_to_http_allowlists() -> None:
    settings = _settings()

    assert settings.public_origin == "http://203.0.113.10:8088"
    assert settings.public_host == "203.0.113.10"
    assert settings.secure_cookies is False
    assert settings.effective_cors_origins == ["http://203.0.113.10:8088"]
    assert "203.0.113.10" in settings.effective_trusted_hosts
    assert "203.0.113.10:*" in settings.mcp_transport_allowed_hosts
    assert "http://203.0.113.10:8088" in settings.mcp_transport_allowed_origins


def test_production_http_requires_explicit_insecure_override() -> None:
    settings = _settings(
        environment="production",
        credential_master_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )

    with pytest.raises(RuntimeError, match="ALLOW_INSECURE_HTTP"):
        settings.assert_production_safe()


def test_production_http_override_keeps_production_checks_but_disables_secure_cookie() -> None:
    settings = _settings(
        environment="production",
        allow_insecure_http=True,
        credential_master_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )

    settings.assert_production_safe()
    assert settings.secure_cookies is False


def test_http_compatibility_refresh_cookie_is_httponly_but_not_secure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(allow_insecure_http=True)
    monkeypatch.setattr(auth_routes, "settings", settings)
    response = Response()

    auth_routes._set_refresh_cookie(
        response,
        "unit-test-refresh-token",
        datetime.now(UTC) + timedelta(days=1),
    )

    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie


@pytest.mark.asyncio
async def test_mcp_preflight_accepts_the_public_http_origin() -> None:
    middleware = McpSecurityMiddleware(_ok_app, _settings())
    transport = httpx.ASGITransport(app=middleware)
    async with httpx.AsyncClient(transport=transport, base_url="http://mcp-server") as client:
        response = await client.options(
            "/mcp",
            headers={
                "Origin": "http://203.0.113.10:8088",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "http://203.0.113.10:8088"
    assert "Authorization" in response.headers["access-control-allow-headers"]


@pytest.mark.asyncio
async def test_mcp_preflight_rejects_an_unknown_origin() -> None:
    middleware = McpSecurityMiddleware(_ok_app, _settings())
    transport = httpx.ASGITransport(app=middleware)
    async with httpx.AsyncClient(transport=transport, base_url="http://mcp-server") as client:
        response = await client.options(
            "/mcp",
            headers={
                "Origin": "http://malicious.example",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_null_origin_requires_an_explicit_compatibility_flag() -> None:
    denied = McpSecurityMiddleware(_ok_app, _settings())
    allowed = McpSecurityMiddleware(_ok_app, _settings(mcp_allow_null_origin=True))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=denied),
        base_url="http://mcp-server",
    ) as client:
        denied_response = await client.options("/mcp", headers={"Origin": "null"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=allowed),
        base_url="http://mcp-server",
    ) as client:
        allowed_response = await client.options("/mcp", headers={"Origin": "null"})

    assert denied_response.status_code == 403
    assert allowed_response.status_code == 204
    assert allowed_response.headers["access-control-allow-origin"] == "null"
