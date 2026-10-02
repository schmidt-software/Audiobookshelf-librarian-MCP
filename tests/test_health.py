"""Health version reporting in installed and source-only deployments."""

import importlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from abs_librarian import __version__

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_health_reports_package_version(monkeypatch):
    monkeypatch.setenv("ABS_URL", "http://abs.example")
    monkeypatch.setenv("ABS_TOKEN", "test-token")
    app = importlib.import_module("abs_librarian.__main__").app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_build_metadata_uses_package_version():
    with (ROOT / "pyproject.toml").open("rb") as file:
        config = tomllib.load(file)

    assert "version" not in config["project"]
    assert "version" in config["project"]["dynamic"]
    assert config["tool"]["hatch"]["version"]["path"] == "src/abs_librarian/__init__.py"


def test_health_without_distribution_metadata_or_project_file():
    """Docker copies only src: neither metadata nor pyproject.toml is available."""
    script = """
import asyncio
import importlib.metadata
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

original_version = importlib.metadata.version

def source_only_version(name):
    if name == "abs-librarian-mcp":
        raise importlib.metadata.PackageNotFoundError(name)
    return original_version(name)

async def check():
    with (
        patch("importlib.metadata.version", side_effect=source_only_version),
        patch("tomllib.load", side_effect=AssertionError("No project file in Docker")),
    ):
        from abs_librarian import __version__
        from abs_librarian.__main__ import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": __version__}

asyncio.run(check())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT / "src",
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "ABS_URL": "http://abs.example",
            "ABS_TOKEN": "test-token",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
