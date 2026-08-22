from __future__ import annotations

import pytest

from apps.mcp_stdio_proxy.main import resolve_remote_mcp_url


def test_remote_http_requires_explicit_opt_in() -> None:
    with pytest.raises(RuntimeError, match="SYNAPSEKB_ALLOW_INSECURE_HTTP=true"):
        resolve_remote_mcp_url(
            "http://124.222.200.16:8088",
            allow_insecure_http=False,
        )


def test_remote_http_is_allowed_after_explicit_opt_in() -> None:
    assert (
        resolve_remote_mcp_url(
            "http://124.222.200.16:8088",
            allow_insecure_http=True,
        )
        == "http://124.222.200.16:8088/mcp"
    )


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_loopback_http_does_not_require_opt_in(host: str) -> None:
    assert resolve_remote_mcp_url(
        f"http://{host}:8088",
        allow_insecure_http=False,
    ).endswith(":8088/mcp")


def test_existing_mcp_path_is_not_duplicated() -> None:
    assert (
        resolve_remote_mcp_url(
            "https://synapsekb.example.com/mcp",
            allow_insecure_http=False,
        )
        == "https://synapsekb.example.com/mcp"
    )


@pytest.mark.parametrize(
    "url",
    [
        "synapsekb.example.com",
        "ftp://synapsekb.example.com",
        "https://user:password@synapsekb.example.com",
        "https://synapsekb.example.com/other",
        "https://synapsekb.example.com?token=secret",
    ],
)
def test_invalid_remote_urls_are_rejected(url: str) -> None:
    with pytest.raises(RuntimeError):
        resolve_remote_mcp_url(url, allow_insecure_http=True)
