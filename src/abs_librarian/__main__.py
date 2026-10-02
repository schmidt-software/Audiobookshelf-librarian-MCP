"""Entry point: python -m abs_librarian"""

import sys

import uvicorn
from starlette.responses import JSONResponse

from . import __version__
from .auth import AuthBackoffSettings, BearerTokenMiddleware
from .server import cfg, mcp

# Use FastMCP's own ASGI app so its lifespan (task group) initialises correctly.
# A thin wrapper intercepts /health before passing through to the MCP handler.
# Everything except /health requires the configured MCP_TOKEN as a bearer token.
_mcp_app = BearerTokenMiddleware(
    mcp.streamable_http_app(),
    cfg.mcp_token,
    backoff_settings=AuthBackoffSettings(
        failure_limit=cfg.mcp_auth_failure_limit,
        failure_window_seconds=cfg.mcp_auth_failure_window_seconds,
        initial_backoff_seconds=cfg.mcp_auth_backoff_seconds,
        max_backoff_seconds=cfg.mcp_auth_max_backoff_seconds,
    ),
)


async def app(scope, receive, send):
    if scope["type"] == "http" and scope.get("path") == "/health":
        response = JSONResponse({"status": "ok", "version": __version__})
        await response(scope, receive, send)
    else:
        await _mcp_app(scope, receive, send)


def main() -> None:
    if not cfg.mcp_token.strip():
        sys.exit("MCP_TOKEN must be set to a non-empty secret; refusing to start.")
    uvicorn.run(app, host="0.0.0.0", port=cfg.port)


if __name__ == "__main__":
    main()
