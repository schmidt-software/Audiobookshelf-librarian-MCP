"""Tests for blob-split and flatten logic using a temp directory tree."""


import pytest

from abs_librarian.audit import AuditLogError
from abs_librarian.fs_tools import (
    fs_flatten,
    fs_make_book_folders,
    fs_move,
    fs_quarantine,
)

AUDIO_EXTS = [".mp3", ".m4b", ".flac"]


def _audit_log(lib):
    return str(lib / "audit.jsonl")


@pytest.fixture()
def blob_dir(tmp_path):
    """A folder with three loose audio files (blob pattern)."""
    lib = tmp_path / "audiobooks"
    blob = lib / "Big Blob Book"
    blob.mkdir(parents=True)
    for i, ext in enumerate(AUDIO_EXTS):
        (blob / f"track{i:02d}{ext}").write_bytes(b"\x00" * 100)
    return blob, lib


@pytest.fixture()
def disc_dir(tmp_path):
    """A folder with two disc subfolders each containing audio files."""
    lib = tmp_path / "audiobooks"
    book = lib / "Series Book 1"
    for disc in ["Disc 1", "Disc 2"]:
        d = book / disc
        d.mkdir(parents=True)
        for i in range(2):
            (d / f"track{i:02d}.mp3").write_bytes(b"\x00" * 100)
    return book, lib


# ------------------------------------------------------------------
# fs_make_book_folders
# ------------------------------------------------------------------

def test_make_book_folders_dry_run(blob_dir, tmp_path):
    book_path, lib = blob_dir
    result = fs_make_book_folders(str(book_path), [str(lib)], _audit_log(lib), confirm=False)
    assert result["dry_run"] is True
    assert result["count"] == 3
    # Files must NOT have moved
    file_count = (
        len(list(book_path.glob("*.mp3")))
        + len(list(book_path.glob("*.m4b")))
        + len(list(book_path.glob("*.flac")))
    )
    assert file_count == 3


def test_make_book_folders_confirm(blob_dir, tmp_path):
    book_path, lib = blob_dir
    result = fs_make_book_folders(str(book_path), [str(lib)], _audit_log(lib), confirm=True)
    assert result["dry_run"] is False
    assert result["count"] == 3
    # Each audio file should now be in its own subfolder
    subfolders = [d for d in book_path.iterdir() if d.is_dir()]
    assert len(subfolders) == 3
    for sf in subfolders:
        audio = list(sf.iterdir())
        assert len(audio) == 1


def test_make_book_folders_no_overwrite(blob_dir, tmp_path):
    book_path, lib = blob_dir
    # Run once to move files
    fs_make_book_folders(str(book_path), [str(lib)], _audit_log(lib), confirm=True)
    # Put a loose file back to trigger the overwrite guard
    track = book_path / "track00.mp3"
    track.write_bytes(b"\x00" * 50)
    result = fs_make_book_folders(str(book_path), [str(lib)], _audit_log(lib), confirm=True)
    skipped = [m for m in result["moves"] if m.get("skipped")]
    assert len(skipped) == 1


# ------------------------------------------------------------------
# fs_flatten
# ------------------------------------------------------------------

def test_flatten_dry_run(disc_dir, tmp_path):
    book_path, lib = disc_dir
    result = fs_flatten(str(book_path), [str(lib)], _audit_log(lib), confirm=False)
    assert result["dry_run"] is True
    assert result["count"] == 4
    # Disc folders still present
    assert (book_path / "Disc 1").exists()
    assert (book_path / "Disc 2").exists()


def test_flatten_confirm(disc_dir, tmp_path):
    book_path, lib = disc_dir
    result = fs_flatten(str(book_path), [str(lib)], _audit_log(lib), confirm=True)
    assert result["dry_run"] is False
    assert result["count"] == 4
    # All files should be in the root book folder now
    files = list(book_path.glob("*.mp3"))
    assert len(files) == 4
    # Disc subfolders should be gone
    assert not (book_path / "Disc 1").exists()
    assert not (book_path / "Disc 2").exists()


def test_flatten_prefixes_filenames(disc_dir, tmp_path):
    book_path, lib = disc_dir
    fs_flatten(str(book_path), [str(lib)], _audit_log(lib), confirm=True)
    names = {f.name for f in book_path.glob("*.mp3")}
    assert any(n.startswith("Disc 1") for n in names)
    assert any(n.startswith("Disc 2") for n in names)


@pytest.mark.parametrize(
    ("operation", "kwargs", "expected_path", "fixture_name"),
    [
        (
            fs_make_book_folders,
            lambda book_path, lib: {
                "path": str(book_path),
                "permitted_roots": [str(lib)],
                "audit_log": _audit_log(lib),
                "confirm": True,
            },
            lambda book_path: book_path / "track00.mp3",
            "blob_dir",
        ),
        (
            fs_flatten,
            lambda book_path, lib: {
                "path": str(book_path),
                "permitted_roots": [str(lib)],
                "audit_log": _audit_log(lib),
                "confirm": True,
            },
            lambda book_path: book_path / "Disc 1" / "track00.mp3",
            "disc_dir",
        ),
        (
            fs_move,
            lambda book_path, lib: {
                "src": str(book_path / "track00.mp3"),
                "dest": str(book_path / "moved" / "track00.mp3"),
                "permitted_roots": [str(lib)],
                "audit_log": _audit_log(lib),
                "confirm": True,
            },
            lambda book_path: book_path / "track00.mp3",
            "blob_dir",
        ),
        (
            fs_quarantine,
            lambda book_path, lib: {
                "path": str(book_path / "track00.mp3"),
                "permitted_roots": [str(lib)],
                "quarantine_dir": str(lib / "quarantine"),
                "audit_log": _audit_log(lib),
                "confirm": True,
            },
            lambda book_path: book_path / "track00.mp3",
            "blob_dir",
        ),
    ],
)
def test_mutating_operations_abort_when_audit_logging_fails(
    monkeypatch, capsys, operation, kwargs, expected_path, fixture_name, request
):
    book_path, lib = request.getfixturevalue(fixture_name)

    def failing_open(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("abs_librarian.audit.Path.open", failing_open)

    with pytest.raises(AuditLogError, match="Operation aborted before mutating the filesystem"):
        operation(**kwargs(book_path, lib))

    assert expected_path(book_path).exists()
    captured = capsys.readouterr()
    assert "CRITICAL: failed to write audit log" in captured.err
    assert "disk full" in captured.err
