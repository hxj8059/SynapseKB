import pytest
from synapsekb.document_processing.url_fetcher import validate_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "ftp://example.com/file",
        "http://user:password@example.com/",
    ],
)
async def test_validate_public_url_rejects_ssrf_targets(url: str) -> None:
    with pytest.raises(ValueError):
        await validate_public_url(url, {80, 443})


async def test_validate_public_url_accepts_public_literal() -> None:
    await validate_public_url("https://93.184.216.34/example", {80, 443})


async def test_validate_public_url_rejects_nonstandard_port() -> None:
    with pytest.raises(ValueError, match="端口"):
        await validate_public_url("https://93.184.216.34:8443/example", {80, 443})
