"""Static bearer-token authentication for the MCP HTTP endpoint.

The MCP Python SDK does not read any environment variable for authentication, so the
configured ``MCP_TOKEN`` is enforced here as ASGI middleware wrapped around the FastMCP
app. The middleware fails closed: if no token is configured, every request is rejected.
"""

from __future__ import annotations

import hmac
import logging

from starlette.responses import JSONResponse
from starlette.websockets import WebSocketClose

logger = logging.getLogger(__name__)

_REALM = "abs-librarian"


def _bearer_token(scope) -> bytes | None:
    """Extract the bearer token from the Authorization header, or None if absent/malformed."""
    for name, value in scope.get("headers") or []:
        if name.lower() == b"authorization":
            scheme, _, credentials = value.strip().partition(b" ")
            if scheme.lower() != b"bearer":
                return None
            credentials = credentials.strip()
            return credentials or None
    return None


class BearerTokenMiddleware:
    """Reject HTTP/WebSocket requests that do not present the configured bearer token.

    Lifespan events are passed through so the wrapped app starts and stops normally.
    """

    def __init__(self, app, token: str | None):
        self.app = app
        token = (token or "").strip()
        self._token = token.encode("utf-8") if token else None
        if self._token is None:
            logger.error(
                "MCP_TOKEN is not configured; all MCP requests will be rejected."
            )

    def _authorized(self, scope) -> bool:
        if self._token is None:
            return False
        presented = _bearer_token(scope)
        if presented is None:
            return False
        return hmac.compare_digest(presented, self._token)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or self._authorized(scope):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await WebSocketClose(code=1008)(scope, receive, send)
            return

        if self._token is None:
            response = JSONResponse(
                {
                    "error": "server_misconfigured",
                    "error_description": "MCP_TOKEN is not configured on the server.",
                },
                status_code=503,
            )
        else:
            response = JSONResponse(
                {
                    "error": "invalid_token",
                    "error_description": "Missing or invalid bearer token.",
                },
                status_code=401,
                headers={
                    "WWW-Authenticate": f'Bearer realm="{_REALM}", error="invalid_token"'
                },
            )
        await response(scope, receive, send)
