"""Dependency constraints and the FastMCP startup surface."""

import os
import shlex
import subprocess
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def mcp_requirement(requirements):
    return next(req for value in requirements if (req := Requirement(value)).name == "mcp")


def test_python_and_docker_require_compatible_mcp():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    python_req = mcp_requirement(project["project"]["dependencies"])
    docker_install = next(
        line for line in (ROOT / "Dockerfile").read_text().splitlines()
        if line.startswith("RUN pip install ")
    )
    docker_req = mcp_requirement(
        value for value in shlex.split(docker_install)[3:] if not value.startswith("--")
    )

    assert python_req == docker_req == Requirement("mcp[cli]>=1.0,<2")
    for allowed in ("1.0", "1.26.0", "1.999.0"):
        assert allowed in python_req.specifier
    for rejected in ("0.9", "2.0", "2.1", "3.0"):
        assert rejected not in python_req.specifier


def test_resolved_mcp_is_compatible():
    assert version("mcp") in Requirement("mcp[cli]>=1.0,<2").specifier


def test_fastmcp_import_and_http_startup():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import asyncio
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient
from abs_librarian.__main__ import app
from abs_librarian.server import mcp

assert isinstance(mcp, FastMCP)
tools = asyncio.run(mcp.list_tools())
assert any(tool.name == "health" for tool in tools)
with TestClient(app) as client:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
""",
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "ABS_URL": "http://localhost:13378",
            "ABS_TOKEN": "test-token",
            "MCP_TOKEN": "",
            "PORT": "8000",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
