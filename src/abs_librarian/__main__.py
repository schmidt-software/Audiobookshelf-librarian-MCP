"""Entry point: python -m abs_librarian"""

import sys

import uvicorn
from starlette.responses import JSONResponse

from . import __version__
from .auth import BearerTokenMiddleware
from .server import cfg, mcp

# Use FastMCP's own ASGI app so its lifespan (task group) initialises correctly.
# A thin wrapper intercepts /health before passing through to the MCP handler.
# Everything except /health requires the configured MCP_TOKEN as a bearer token.
_mcp_app = BearerTokenMiddleware(mcp.streamable_http_app(), cfg.mcp_token)


async def app(scope, receive, send):
    if scope["type"] == "http" and scope.get("path") == "/health":
        response = JSONResponse({"status": "ok", "version": __version__})
        await response(scope, receive, send)
    else:
        # FastMCP rejects non-localhost Host headers (DNS-rebinding protection).
        # Rewrite to localhost:<port> so LAN connections match the localhost:* allowlist.
        if scope.get("headers"):
            new_headers = []
            for k, v in scope["headers"]:
                if k.lower() == b"host":
                    port = v.split(b":")[-1] if b":" in v else b"8000"
                    v = b"localhost:" + port
                new_headers.append((k, v))
            scope = {**scope, "headers": new_headers}
        await _mcp_app(scope, receive, send)


if __name__ == "__main__":
    if not cfg.mcp_token.strip():
        sys.exit("MCP_TOKEN must be set to a non-empty secret; refusing to start.")
    uvicorn.run(app, host="0.0.0.0", port=cfg.port)
