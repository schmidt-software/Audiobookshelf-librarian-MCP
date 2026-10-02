"""Static bearer-token authentication for the MCP HTTP endpoint.

The MCP Python SDK does not read any environment variable for authentication, so the
configured ``MCP_TOKEN`` is enforced here as ASGI middleware wrapped around the FastMCP
app. The middleware fails closed: if no token is configured, every request is rejected.
"""

from __future__ import annotations

import hmac
import logging
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from starlette.responses import JSONResponse
from starlette.websockets import WebSocketClose

logger = logging.getLogger(__name__)

_REALM = "abs-librarian"


@dataclass(frozen=True)
class AuthBackoffSettings:
    """Configuration for per-client failed-auth throttling."""

    failure_limit: int = 5
    failure_window_seconds: float = 300.0
    initial_backoff_seconds: float = 60.0
    max_backoff_seconds: float = 900.0

    def __post_init__(self) -> None:
        if self.failure_limit < 1:
            raise ValueError("failure_limit must be at least 1")
        if self.failure_window_seconds <= 0:
            raise ValueError("failure_window_seconds must be positive")
        if self.initial_backoff_seconds <= 0:
            raise ValueError("initial_backoff_seconds must be positive")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError(
                "max_backoff_seconds must be greater than or equal to initial_backoff_seconds"
            )


@dataclass
class _ClientAuthState:
    failures: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0


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


def _client_ip(scope) -> str:
    client = scope.get("client")
    if isinstance(client, tuple) and client and client[0]:
        return str(client[0])
    return "unknown"


class BearerTokenMiddleware:
    """Reject HTTP/WebSocket requests that do not present the configured bearer token.

    Lifespan events are passed through so the wrapped app starts and stops normally.
    """

    def __init__(
        self,
        app,
        token: str | None,
        *,
        backoff_settings: AuthBackoffSettings | None = None,
        clock: Callable[[], float] | None = None,
    ):
        self.app = app
        token = (token or "").strip()
        self._token = token.encode("utf-8") if token else None
        self._backoff = backoff_settings or AuthBackoffSettings()
        self._clock = clock or time.monotonic
        self._failures: dict[str, _ClientAuthState] = {}
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

    def _prune_failures(self, state: _ClientAuthState, now: float) -> None:
        cutoff = now - self._backoff.failure_window_seconds
        while state.failures and state.failures[0] < cutoff:
            state.failures.popleft()

    def _clear_failures(self, scope) -> None:
        self._failures.pop(_client_ip(scope), None)

    def _blocked_retry_after(self, scope) -> int | None:
        client_ip = _client_ip(scope)
        state = self._failures.get(client_ip)
        if state is None:
            return None
        now = self._clock()
        self._prune_failures(state, now)
        if state.blocked_until <= now:
            if not state.failures:
                self._failures.pop(client_ip, None)
            return None
        return max(1, math.ceil(state.blocked_until - now))

    def _register_failure(self, scope) -> int | None:
        now = self._clock()
        state = self._failures.setdefault(_client_ip(scope), _ClientAuthState())
        self._prune_failures(state, now)
        state.failures.append(now)
        if len(state.failures) <= self._backoff.failure_limit:
            return None

        overflow = len(state.failures) - self._backoff.failure_limit
        backoff_seconds = min(
            self._backoff.max_backoff_seconds,
            self._backoff.initial_backoff_seconds * (2 ** (overflow - 1)),
        )
        state.blocked_until = max(state.blocked_until, now + backoff_seconds)
        return max(1, math.ceil(state.blocked_until - now))

    async def _reject_http(self, scope, receive, send, retry_after: int | None = None):
        if self._token is None:
            response = JSONResponse(
                {
                    "error": "server_misconfigured",
                    "error_description": "MCP_TOKEN is not configured on the server.",
                },
                status_code=503,
            )
        elif retry_after is not None:
            response = JSONResponse(
                {
                    "error": "too_many_attempts",
                    "error_description": "Too many failed authentication attempts.",
                },
                status_code=429,
                headers={
                    "Retry-After": str(retry_after),
                    "WWW-Authenticate": f'Bearer realm="{_REALM}", error="slow_down"',
                },
            )
        else:
            response = JSONResponse(
                {
                    "error": "invalid_token",
                    "error_description": "Missing or invalid bearer token.",
                },
                status_code=401,
                headers={
                    "WWW-Authenticate": (
                        f'Bearer realm="{_REALM}", error="invalid_token"'
                    )
                },
            )
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if self._authorized(scope):
            self._clear_failures(scope)
            await self.app(scope, receive, send)
            return

        retry_after = None
        if self._token is not None:
            retry_after = self._blocked_retry_after(scope)
            if retry_after is None:
                retry_after = self._register_failure(scope)

        if scope["type"] == "websocket":
            await WebSocketClose(code=1008)(scope, receive, send)
            return

        if retry_after is not None:
            logger.warning(
                "Rate-limiting failed MCP authentication from %s for %ss",
                _client_ip(scope),
                retry_after,
            )
        await self._reject_http(scope, receive, send, retry_after)
