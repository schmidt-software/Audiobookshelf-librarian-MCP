"""Tests for fs_move, fs_quarantine, and detect_blobs."""

from __future__ import annotations

from abs_librarian.fs_tools import detect_blobs, fs_move, fs_quarantine


def test_fs_move_dry_run_reports_paths_without_moving(tmp_path):
    library = tmp_path / "library"
    source = library / "Author" / "Book.m4b"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    destination = library / "Moved" / "Book.m4b"
    audit_log = tmp_path / "audit.jsonl"

    result = fs_move(str(source), str(destination), [str(library)], str(audit_log), confirm=False)

    assert result == {
        "dry_run": True,
        "src": str(source.resolve()),
        "dest": str(destination.resolve()),
    }
    assert source.exists()
    assert not destination.exists()


def test_fs_move_confirm_creates_parent_directories_and_moves_file(tmp_path):
    library = tmp_path / "library"
    source = library / "Author" / "Book.m4b"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    destination = library / "Moved" / "Book.m4b"
    audit_log = tmp_path / "audit.jsonl"

    result = fs_move(str(source), str(destination), [str(library)], str(audit_log), confirm=True)

    assert result == {
        "dry_run": False,
        "src": str(source.resolve()),
        "dest": str(destination.resolve()),
        "ok": True,
    }
    assert not source.exists()
    assert destination.read_bytes() == b"audio"


def test_fs_move_refuses_to_overwrite_existing_destination(tmp_path):
    library = tmp_path / "library"
    source = library / "Author" / "Book.m4b"
    destination = library / "Moved" / "Book.m4b"
    source.parent.mkdir(parents=True)
    destination.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    destination.write_bytes(b"existing")
    audit_log = tmp_path / "audit.jsonl"

    result = fs_move(str(source), str(destination), [str(library)], str(audit_log), confirm=True)

    assert result["error"] == "destination exists; move aborted (no overwrite)"
    assert source.read_bytes() == b"source"
    assert destination.read_bytes() == b"existing"


def test_fs_quarantine_dry_run_preserves_relative_destination(tmp_path):
    library = tmp_path / "library"
    quarantine = tmp_path / "quarantine"
    source = library / "Series" / "Book" / "track01.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    audit_log = tmp_path / "audit.jsonl"

    result = fs_quarantine(
        str(source),
        [str(library)],
        str(quarantine),
        str(audit_log),
        confirm=False,
    )

    assert result == {
        "dry_run": True,
        "src": str(source.resolve()),
        "dest": str((quarantine / "Series" / "Book" / "track01.mp3").resolve()),
    }
    assert source.exists()


def test_fs_quarantine_confirm_moves_file_into_quarantine_tree(tmp_path):
    library = tmp_path / "library"
    quarantine = tmp_path / "quarantine"
    source = library / "Series" / "Book" / "track01.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    audit_log = tmp_path / "audit.jsonl"

    result = fs_quarantine(
        str(source),
        [str(library)],
        str(quarantine),
        str(audit_log),
        confirm=True,
    )

    destination = quarantine / "Series" / "Book" / "track01.mp3"
    assert result == {
        "dry_run": False,
        "src": str(source.resolve()),
        "dest": str(destination.resolve()),
        "ok": True,
    }
    assert not source.exists()
    assert destination.read_bytes() == b"audio"


def test_fs_quarantine_refuses_to_overwrite_existing_destination(tmp_path):
    library = tmp_path / "library"
    quarantine = tmp_path / "quarantine"
    source = library / "Series" / "Book" / "track01.mp3"
    destination = quarantine / "Series" / "Book" / "track01.mp3"
    source.parent.mkdir(parents=True)
    destination.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    destination.write_bytes(b"existing")
    audit_log = tmp_path / "audit.jsonl"

    result = fs_quarantine(
        str(source),
        [str(library)],
        str(quarantine),
        str(audit_log),
        confirm=True,
    )

    assert result["error"] == "destination exists in quarantine; aborted"
    assert source.read_bytes() == b"source"
    assert destination.read_bytes() == b"existing"


def test_detect_blobs_flags_large_folders_and_disc_subfolders(tmp_path):
    library = tmp_path / "library"
    blob_book = library / "Blob Book"
    blob_book.mkdir(parents=True)
    for index in range(4):
        (blob_book / f"track{index:02d}.mp3").write_bytes(b"\x00" * 128)

    structured_book = library / "Structured Book"
    disc = structured_book / "Disc 1"
    disc.mkdir(parents=True)
    for index in range(3):
        (disc / f"track{index:02d}.m4b").write_bytes(b"\x00" * 128)

    ignored = library / "Notes"
    ignored.mkdir()
    (ignored / "readme.txt").write_text("not audio", encoding="utf-8")

    result = detect_blobs(
        str(library),
        [str(library)],
        hours_threshold=100.0,
        file_count_threshold=3,
    )

    assert result["count"] == 2
    suspects = {entry["path"]: entry for entry in result["suspects"]}
    assert suspects[str(blob_book.resolve())]["audio_count"] == 4
    assert suspects[str(blob_book.resolve())]["has_disc_subfolders"] is False
    assert suspects[str(structured_book.resolve())]["audio_count"] == 3
    assert suspects[str(structured_book.resolve())]["has_disc_subfolders"] is True
