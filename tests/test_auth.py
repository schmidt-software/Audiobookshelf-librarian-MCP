"""Raw HTTP/ASGI tests for MCP bearer-token authentication."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

# server.py builds its Config at import time; provide the required settings first.
# MCP_TOKEN is deliberately not set here: the client fixture installs its own token so
# these tests do not depend on (or leak into) environment shared with other test modules.
TOKEN = "test-secret-token-0123456789"
os.environ.setdefault("ABS_URL", "http://abs.invalid")
os.environ.setdefault("ABS_TOKEN", "abs-test-token")

from mcp.server.fastmcp import FastMCP  # noqa: E402

from abs_librarian import __main__ as entry  # noqa: E402
from abs_librarian import server as server_module  # noqa: E402
from abs_librarian.auth import AuthBackoffSettings, BearerTokenMiddleware  # noqa: E402

BASE_URL = "http://localhost:8000"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
TOOLS_CALL = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {"name": "tool_fs_tree", "arguments": {"path": "/nonexistent"}},
}


def _auth(token: str) -> dict[str, str]:
    return {**MCP_HEADERS, "Authorization": f"Bearer {token}"}


async def _send_http_request(app, headers: dict[str, str], client=("127.0.0.1", 12345)):
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": [
            (name.lower().encode("ascii"), value.encode("latin-1"))
            for name, value in headers.items()
        ],
        "client": client,
        "server": ("localhost", 8000),
    }

    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    response_headers = {
        name.decode("latin-1").lower(): value.decode("latin-1")
        for name, value in start.get("headers", [])
    }
    return start["status"], response_headers, json.loads(body.decode("utf-8"))


def test_entrypoint_wraps_mcp_app_with_auth():
    assert isinstance(entry._mcp_app, BearerTokenMiddleware)


@pytest.fixture(scope="module")
def client():
    # A FastMCP session manager can only run once per process, so build a fresh MCP app
    # (and auth wrapper with a known token) instead of reusing the module-level instance.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(server_module.mcp, "_session_manager", None)
        fresh = BearerTokenMiddleware(
            server_module.mcp.streamable_http_app(),
            TOKEN,
            backoff_settings=AuthBackoffSettings(failure_limit=1000),
        )
        mp.setattr(entry, "_mcp_app", fresh)
        # Entering the context manager runs the ASGI lifespan through entry.app and the auth
        # wrapper.
        with TestClient(entry.app, base_url=BASE_URL) as c:
            yield c


def test_health_is_public(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.parametrize("payload", [INITIALIZE, TOOLS_LIST, TOOLS_CALL])
@pytest.mark.parametrize(
    "headers",
    [
        MCP_HEADERS,
        _auth("wrong-token"),
        _auth(TOKEN + "x"),
        _auth(""),
        {**MCP_HEADERS, "Authorization": TOKEN},
        {**MCP_HEADERS, "Authorization": f"Basic {TOKEN}"},
    ],
    ids=["missing", "wrong", "prefix", "empty", "no-scheme", "basic"],
)
def test_mcp_requests_rejected_without_valid_token(client, payload, headers):
    resp = client.post("/mcp", json=payload, headers=headers)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Bearer ")
    assert TOKEN not in resp.text
    assert resp.json()["error"] == "invalid_token"


def test_other_paths_require_auth(client):
    assert client.get("/mcp", headers=MCP_HEADERS).status_code == 401
    assert client.get("/anything").status_code == 401


def test_failed_auth_rate_limited_with_retry_after():
    now = [1000.0]

    async def inner(scope, receive, send):
        response = JSONResponse({"ok": True})
        await response(scope, receive, send)

    middleware = BearerTokenMiddleware(
        inner,
        TOKEN,
        backoff_settings=AuthBackoffSettings(
            failure_limit=2,
            failure_window_seconds=300,
            initial_backoff_seconds=30,
            max_backoff_seconds=120,
        ),
        clock=lambda: now[0],
    )

    status, headers, body = asyncio.run(_send_http_request(middleware, _auth("wrong-1")))
    assert status == 401
    assert headers["www-authenticate"].startswith("Bearer ")
    assert body["error"] == "invalid_token"

    status, _, _ = asyncio.run(_send_http_request(middleware, _auth("wrong-2")))
    assert status == 401

    status, headers, body = asyncio.run(_send_http_request(middleware, _auth("wrong-3")))
    assert status == 429
    assert headers["retry-after"] == "30"
    assert body["error"] == "too_many_attempts"

    now[0] += 10
    status, headers, body = asyncio.run(_send_http_request(middleware, _auth("wrong-4")))
    assert status == 429
    assert headers["retry-after"] == "20"
    assert body["error"] == "too_many_attempts"

    now[0] += 20
    status, _, body = asyncio.run(_send_http_request(middleware, _auth(TOKEN)))
    assert status == 200
    assert body == {"ok": True}

    status, _, body = asyncio.run(_send_http_request(middleware, _auth("wrong-5")))
    assert status == 401
    assert body["error"] == "invalid_token"


def test_failed_auth_tracking_is_per_client_ip():
    now = [2000.0]

    async def inner(scope, receive, send):
        response = JSONResponse({"ok": True})
        await response(scope, receive, send)

    middleware = BearerTokenMiddleware(
        inner,
        TOKEN,
        backoff_settings=AuthBackoffSettings(
            failure_limit=1,
            failure_window_seconds=300,
            initial_backoff_seconds=45,
            max_backoff_seconds=120,
        ),
        clock=lambda: now[0],
    )

    status, _, _ = asyncio.run(
        _send_http_request(middleware, _auth("wrong-a"), client=("10.0.0.10", 1111))
    )
    assert status == 401

    status, headers, body = asyncio.run(
        _send_http_request(middleware, _auth("wrong-b"), client=("10.0.0.10", 1111))
    )
    assert status == 429
    assert headers["retry-after"] == "45"
    assert body["error"] == "too_many_attempts"

    status, _, body = asyncio.run(
        _send_http_request(middleware, _auth("wrong-c"), client=("10.0.0.11", 1111))
    )
    assert status == 401
    assert body["error"] == "invalid_token"


def test_valid_token_initialize(client):
    resp = client.post("/mcp", json=INITIALIZE, headers=_auth(TOKEN))
    assert resp.status_code == 200
    assert "serverInfo" in resp.text


def test_valid_token_case_insensitive_scheme(client):
    headers = {**MCP_HEADERS, "Authorization": f"bearer {TOKEN}"}
    resp = client.post("/mcp", json=INITIALIZE, headers=headers)
    assert resp.status_code == 200


def test_valid_token_tools_list_and_call(client):
    resp = client.post("/mcp", json=TOOLS_LIST, headers=_auth(TOKEN))
    assert resp.status_code == 200
    assert '"name":"tool_fs_tree"' in resp.text

    resp = client.post("/mcp", json=TOOLS_CALL, headers=_auth(TOKEN))
    assert resp.status_code == 200
    body = resp.text.replace(" ", "")
    assert '"id":3' in body
    assert '"result"' in body


@pytest.mark.parametrize("configured", ["", "   ", None])
def test_fail_closed_when_token_not_configured(configured):
    server = FastMCP("unconfigured", stateless_http=True)

    @server.tool()
    def ping() -> str:
        return "pong"

    app = BearerTokenMiddleware(server.streamable_http_app(), configured)
    with TestClient(app, base_url=BASE_URL) as c:
        for headers in (MCP_HEADERS, _auth(""), _auth("anything")):
            resp = c.post("/mcp", json=INITIALIZE, headers=headers)
            assert resp.status_code == 503
            assert resp.json()["error"] == "server_misconfigured"
        resp = c.post("/mcp", json=TOOLS_LIST, headers=_auth("anything"))
        assert resp.status_code == 503


def test_lifespan_passes_through():
    events: list[str] = []

    async def inner(scope, receive, send):
        assert scope["type"] == "lifespan"
        events.append("lifespan")

    asyncio.run(BearerTokenMiddleware(inner, "")({"type": "lifespan"}, None, None))
    assert events == ["lifespan"]


def test_websocket_rejected_without_token():
    sent: list[dict] = []

    async def inner(scope, receive, send):  # pragma: no cover - must not be reached
        raise AssertionError("inner app called")

    async def send(message):
        sent.append(message)

    middleware = BearerTokenMiddleware(inner, TOKEN)
    asyncio.run(middleware({"type": "websocket", "headers": []}, None, send))
    assert sent[0]["type"] == "websocket.close"
    assert sent[0]["code"] == 1008


def test_entrypoint_refuses_to_start_without_token():
    src = str(Path(entry.__file__).resolve().parents[1])
    env = {
        **os.environ,
        "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "MCP_TOKEN": "  ",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "abs_librarian"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0
    assert "MCP_TOKEN must be set" in proc.stderr
