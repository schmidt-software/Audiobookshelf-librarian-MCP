"""Security regressions for health errors and cover URL validation."""

from __future__ import annotations

import importlib
import logging
import socket
import sys
from unittest.mock import AsyncMock

import pytest

from abs_librarian.config import Config
from abs_librarian.url_security import (
    parse_cover_url_allowed_hosts,
    validate_cover_url,
)


@pytest.fixture()
def config_env(monkeypatch):
    monkeypatch.setenv("ABS_URL", "http://abs.local")
    monkeypatch.setenv("ABS_TOKEN", "test-token")
    monkeypatch.setenv("MCP_TOKEN", "test-token")
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.delenv("COVER_URL_ALLOWED_HOSTS", raising=False)


@pytest.fixture()
def server_module(config_env, monkeypatch):
    for name in ("abs_librarian.__main__", "abs_librarian.server"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module("abs_librarian.server")
    yield module
    for name in ("abs_librarian.__main__", "abs_librarian.server"):
        sys.modules.pop(name, None)


def test_config_parses_cover_url_allowlist(config_env, monkeypatch):
    monkeypatch.setenv(
        "COVER_URL_ALLOWED_HOSTS",
        " covers.internal,192.168.1.25,[fd00::1],covers.internal ",
    )

    assert Config.from_env().cover_url_allowed_hosts == [
        "covers.internal",
        "192.168.1.25",
        "fd00::1",
    ]


@pytest.mark.parametrize(
    "value",
    ["http://covers.internal", "covers.internal:443", "host/path", "*"],
)
def test_cover_url_allowlist_rejects_invalid_entries(value):
    with pytest.raises(ValueError):
        parse_cover_url_allowed_hosts(value)


def test_validate_cover_url_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="http or https"):
        validate_cover_url("ftp://example.com/cover.jpg")


def test_validate_cover_url_rejects_private_host():
    with pytest.raises(ValueError, match="private, loopback, or link-local"):
        validate_cover_url("http://127.0.0.1/cover.jpg")


def test_validate_cover_url_accepts_public_host(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )

    assert validate_cover_url("https://example.com/cover.jpg") == "https://example.com/cover.jpg"


@pytest.mark.asyncio
async def test_health_sanitizes_exceptions_and_logs_details(server_module, monkeypatch, caplog):
    client = AsyncMock()
    client.get_libraries.side_effect = RuntimeError("dial tcp abs.internal.local:443 failed")
    monkeypatch.setattr(server_module, "_client", lambda: client)
    caplog.set_level(logging.ERROR, logger=server_module.__name__)

    result = await server_module.health()

    assert result == {"status": "error", "detail": "Audiobookshelf connectivity failed"}
    assert "abs.internal.local" not in str(result)
    assert "abs.internal.local" in caplog.text


@pytest.mark.asyncio
async def test_set_cover_rejects_private_direct_url(server_module, monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr(server_module, "_client", lambda: client)
    monkeypatch.setattr(server_module.cfg, "cover_url_allowed_hosts", [])

    result = await server_module.set_cover("item1", url="http://127.0.0.1/cover.jpg")

    assert result == {
        "error": "cover URL host must not resolve to a private, loopback, or link-local address",
        "item_id": "item1",
    }
    client.set_cover_url.assert_not_called()


@pytest.mark.asyncio
async def test_set_cover_accepts_allowlisted_private_direct_url(server_module, monkeypatch):
    client = AsyncMock()
    client.set_cover_url.return_value = {"ok": True}
    monkeypatch.setattr(server_module, "_client", lambda: client)
    monkeypatch.setattr(server_module.cfg, "cover_url_allowed_hosts", ["192.168.1.25"])

    result = await server_module.set_cover("item1", url="http://192.168.1.25/cover.jpg")

    assert result == {"item_id": "item1", "source": "url", "result": {"ok": True}}
    client.set_cover_url.assert_awaited_once_with("item1", "http://192.168.1.25/cover.jpg")


@pytest.mark.asyncio
async def test_set_cover_rejects_private_search_result(server_module, monkeypatch):
    client = AsyncMock()
    client.search_covers.return_value = [{"url": "http://169.254.10.20/cover.jpg"}]
    monkeypatch.setattr(server_module, "_client", lambda: client)
    monkeypatch.setattr(server_module.cfg, "cover_url_allowed_hosts", [])

    result = await server_module.set_cover("item1", search_title="Book", search_author="Author")

    assert result == {
        "error": "cover URL host must not resolve to a private, loopback, or link-local address",
        "item_id": "item1",
    }
    client.set_cover_url.assert_not_called()
