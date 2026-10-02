"""Regression coverage for find_items input validation and bounded matching."""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture()
def server_module(monkeypatch):
    monkeypatch.setenv("ABS_URL", "http://abs.local")
    monkeypatch.setenv("ABS_TOKEN", "test-token")
    monkeypatch.setenv("MCP_TOKEN", "test-token")
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.delenv("ABS_LIBRARY_ITEMS_LIMIT", raising=False)
    monkeypatch.delitem(sys.modules, "abs_librarian.server", raising=False)
    module = importlib.import_module("abs_librarian.server")
    yield module
    sys.modules.pop("abs_librarian.server", None)


@pytest.mark.asyncio
async def test_find_items_rejects_invalid_regex_before_loading_items(server_module, monkeypatch):
    def fail_client():  # pragma: no cover - the assertion is that this is never reached
        raise AssertionError("_client should not be called for invalid regexes")

    monkeypatch.setattr(server_module, "_client", fail_client)

    with pytest.raises(ValueError, match=r"Invalid title_regex: .*unterminated"):
        await server_module.find_items("lib1", title_regex="(")


@pytest.mark.asyncio
async def test_find_items_rejects_overlong_regex_before_loading_items(server_module, monkeypatch):
    def fail_client():  # pragma: no cover - the assertion is that this is never reached
        raise AssertionError("_client should not be called for invalid regexes")

    monkeypatch.setattr(server_module, "_client", fail_client)

    with pytest.raises(ValueError, match="Invalid title_regex: pattern exceeds 256 characters"):
        await server_module.find_items("lib1", title_regex="a" * 257)


@pytest.mark.asyncio
async def test_find_items_rejects_nested_quantifiers(server_module, monkeypatch):
    class FakeClient:
        async def get_library_items(self, library_id: str) -> list[dict]:  # pragma: no cover
            raise AssertionError("library loading should not happen for rejected regexes")

    monkeypatch.setattr(server_module, "_client", lambda: FakeClient())

    with pytest.raises(
        ValueError,
        match="Invalid title_regex: nested quantifiers and backreferences are not allowed",
    ):
        await server_module.find_items("lib1", title_regex=r"(a+)+$")


@pytest.mark.asyncio
async def test_find_items_bounds_title_matching(server_module, monkeypatch):
    class FakeClient:
        async def get_library_items(self, library_id: str) -> list[dict]:
            return [
                {
                    "id": "item1",
                    "path": "/library/short-title",
                    "media": {"metadata": {"title": "Prefix Target"}},
                    "isMissing": False,
                },
                {
                    "id": "item2",
                    "path": "/library/long-title",
                    "media": {"metadata": {"title": ("a" * 1024) + "Target"}},
                    "isMissing": False,
                },
            ]

    monkeypatch.setattr(server_module, "_client", lambda: FakeClient())

    result = await server_module.find_items("lib1", title_regex=r"Target$")

    assert result["count"] == 1
    assert [item["id"] for item in result["items"]] == ["item1"]
