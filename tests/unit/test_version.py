import json
import tomllib
from pathlib import Path

from synapsekb import __version__
from synapsekb.api.app import create_app

from apps.mcp_stdio_proxy.main import server


def test_release_versions_are_consistent() -> None:
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    lock = tomllib.loads((root / "uv.lock").read_text())
    web = json.loads((root / "apps/web/package.json").read_text())
    package = next(item for item in lock["package"] if item["name"] == "synapsekb")
    assert project["project"]["version"] == package["version"] == web["version"] == __version__
    assert create_app().openapi()["info"]["version"] == server.version == __version__
    compose = (root / "docker-compose.yml").read_text()
    assert f"image: synapsekb-backend:{__version__}" in compose
    assert f"image: synapsekb-web:{__version__}" in compose
