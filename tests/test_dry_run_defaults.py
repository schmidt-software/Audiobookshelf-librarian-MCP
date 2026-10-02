"""Mutating tools honor DRY_RUN_DEFAULT when dry_run is omitted."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("ABS_URL", "http://abs.invalid")
os.environ.setdefault("ABS_TOKEN", "abs-test-token")
os.environ.setdefault("MCP_TOKEN", "test-secret-token-0123456789")

from abs_librarian import server as server_module  # noqa: E402


class RecordingClient:
    def __init__(self, missing_items: list[dict] | None = None):
        self.deleted: list[str] = []
        self.backups = 0
        self.missing_items = missing_items or []

    async def delete_item(self, item_id: str) -> None:
        self.deleted.append(item_id)

    async def get_library_items_missing(self, library_id: str) -> list[dict]:
        assert library_id == "lib-1"
        return self.missing_items

    async def create_backup(self) -> dict:
        self.backups += 1
        return {"ok": True}


def _configure_fs(monkeypatch: pytest.MonkeyPatch, library_root: Path, tmp_path: Path) -> Path:
    quarantine_dir = tmp_path / "quarantine"
    monkeypatch.setattr(server_module, "_permitted", lambda: [str(library_root)])
    monkeypatch.setattr(server_module.cfg, "audit_log", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(server_module.cfg, "quarantine_dir", str(quarantine_dir))
    return quarantine_dir


@pytest.mark.asyncio
async def test_delete_item_uses_config_default_when_dry_run_omitted(monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(server_module, "_client", lambda: client)
    monkeypatch.setattr(server_module.cfg, "dry_run_default", True)

    result = await server_module.delete_item("item-1")

    assert result == {"dry_run": True, "would_delete": "item-1"}
    assert client.deleted == []


@pytest.mark.asyncio
async def test_purge_missing_uses_config_default_when_dry_run_omitted(monkeypatch):
    client = RecordingClient(missing_items=[{"id": "item-1"}, {"id": "item-2"}])
    monkeypatch.setattr(server_module, "_client", lambda: client)
    monkeypatch.setattr(server_module.cfg, "dry_run_default", False)

    result = await server_module.purge_missing("lib-1")

    assert result == {"deleted": 2, "errors": []}
    assert client.deleted == ["item-1", "item-2"]


@pytest.mark.asyncio
async def test_create_backup_uses_config_default_and_explicit_override(monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(server_module, "_client", lambda: client)
    monkeypatch.setattr(server_module.cfg, "dry_run_default", True)

    dry_run_result = await server_module.create_backup()
    execute_result = await server_module.create_backup(dry_run=False)

    assert dry_run_result == {"dry_run": True, "would_create": "backup"}
    assert execute_result == {"ok": True}
    assert client.backups == 1


@pytest.mark.asyncio
async def test_fs_make_book_folders_uses_config_default_when_dry_run_omitted(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    book_path = library_root / "Big Blob Book"
    book_path.mkdir(parents=True)
    (book_path / "track01.mp3").write_bytes(b"audio")
    _configure_fs(monkeypatch, library_root, tmp_path)
    monkeypatch.setattr(server_module.cfg, "dry_run_default", True)

    result = await server_module.tool_fs_make_book_folders(str(book_path))

    assert result["dry_run"] is True
    assert (book_path / "track01.mp3").exists()
    assert not (book_path / "track01").exists()


@pytest.mark.asyncio
async def test_fs_flatten_uses_config_default_when_dry_run_omitted(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    book_path = library_root / "Series Book 1"
    disc_path = book_path / "Disc 1"
    disc_path.mkdir(parents=True)
    (disc_path / "track01.mp3").write_bytes(b"audio")
    _configure_fs(monkeypatch, library_root, tmp_path)
    monkeypatch.setattr(server_module.cfg, "dry_run_default", False)

    result = await server_module.tool_fs_flatten(str(book_path))

    assert result["dry_run"] is False
    assert not disc_path.exists()
    assert (book_path / "Disc 1 - track01.mp3").exists()


@pytest.mark.asyncio
async def test_fs_move_uses_explicit_dry_run_over_config(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    library_root.mkdir()
    src = library_root / "source.mp3"
    dest = library_root / "dest.mp3"
    src.write_bytes(b"audio")
    _configure_fs(monkeypatch, library_root, tmp_path)
    monkeypatch.setattr(server_module.cfg, "dry_run_default", False)

    result = await server_module.tool_fs_move(str(src), str(dest), dry_run=True)

    assert result["dry_run"] is True
    assert src.exists()
    assert not dest.exists()


@pytest.mark.asyncio
async def test_fs_quarantine_confirm_alias_executes(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    author_dir = library_root / "Author Name"
    author_dir.mkdir(parents=True)
    source = author_dir / "Book 1.mp3"
    source.write_bytes(b"audio")
    quarantine_dir = _configure_fs(monkeypatch, library_root, tmp_path)
    monkeypatch.setattr(server_module.cfg, "dry_run_default", True)

    result = await server_module.tool_fs_quarantine(str(source), confirm=True)

    assert result["dry_run"] is False
    assert not source.exists()
    assert (quarantine_dir / "Author Name" / "Book 1.mp3").exists()


@pytest.mark.asyncio
async def test_conflicting_dry_run_and_confirm_returns_error():
    result = await server_module.delete_item("item-1", dry_run=True, confirm=True)

    assert result == {"error": "dry_run conflicts with confirm"}
