"""Tests for blob-split, flatten, move, and quarantine logic."""


from pathlib import Path

import pytest

from abs_librarian.fs_tools import fs_flatten, fs_make_book_folders, fs_move, fs_quarantine
from abs_librarian.jail import PathJailError

AUDIO_EXTS = [".mp3", ".m4b", ".flac"]


@pytest.fixture()
def audit_log(tmp_path):
    return str(tmp_path / "audit.jsonl")


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

def test_make_book_folders_dry_run(blob_dir, audit_log):
    book_path, lib = blob_dir
    result = fs_make_book_folders(str(book_path), [str(lib)], audit_log, confirm=False)
    assert result["dry_run"] is True
    assert result["count"] == 3
    # Files must NOT have moved
    file_count = (
        len(list(book_path.glob("*.mp3")))
        + len(list(book_path.glob("*.m4b")))
        + len(list(book_path.glob("*.flac")))
    )
    assert file_count == 3


def test_make_book_folders_confirm(blob_dir, audit_log):
    book_path, lib = blob_dir
    result = fs_make_book_folders(str(book_path), [str(lib)], audit_log, confirm=True)
    assert result["dry_run"] is False
    assert result["count"] == 3
    # Each audio file should now be in its own subfolder
    subfolders = [d for d in book_path.iterdir() if d.is_dir()]
    assert len(subfolders) == 3
    for sf in subfolders:
        audio = list(sf.iterdir())
        assert len(audio) == 1


def test_make_book_folders_no_overwrite(blob_dir, audit_log):
    book_path, lib = blob_dir
    # Run once to move files
    fs_make_book_folders(str(book_path), [str(lib)], audit_log, confirm=True)
    # Put a loose file back to trigger the overwrite guard
    track = book_path / "track00.mp3"
    track.write_bytes(b"\x00" * 50)
    result = fs_make_book_folders(str(book_path), [str(lib)], audit_log, confirm=True)
    skipped = [m for m in result["moves"] if m.get("skipped")]
    assert len(skipped) == 1


# ------------------------------------------------------------------
# fs_flatten
# ------------------------------------------------------------------

def test_flatten_dry_run(disc_dir, audit_log):
    book_path, lib = disc_dir
    result = fs_flatten(str(book_path), [str(lib)], audit_log, confirm=False)
    assert result["dry_run"] is True
    assert result["count"] == 4
    # Disc folders still present
    assert (book_path / "Disc 1").exists()
    assert (book_path / "Disc 2").exists()


def test_flatten_confirm(disc_dir, audit_log):
    book_path, lib = disc_dir
    result = fs_flatten(str(book_path), [str(lib)], audit_log, confirm=True)
    assert result["dry_run"] is False
    assert result["count"] == 4
    # All files should be in the root book folder now
    files = list(book_path.glob("*.mp3"))
    assert len(files) == 4
    # Disc subfolders should be gone
    assert not (book_path / "Disc 1").exists()
    assert not (book_path / "Disc 2").exists()


def test_flatten_prefixes_filenames(disc_dir, audit_log):
    book_path, lib = disc_dir
    fs_flatten(str(book_path), [str(lib)], audit_log, confirm=True)
    names = {f.name for f in book_path.glob("*.mp3")}
    assert any(n.startswith("Disc 1") for n in names)
    assert any(n.startswith("Disc 2") for n in names)


@pytest.fixture()
def move_tree(tmp_path):
    lib = tmp_path / "audiobooks"
    lib.mkdir()
    src_dir = lib / "Book One"
    src_dir.mkdir()
    source = src_dir / "chapter01.mp3"
    source.write_bytes(b"\x00" * 100)
    alternate_dir = lib / "Book Two"
    alternate_dir.mkdir()
    alternate_source = alternate_dir / "chapter99.mp3"
    alternate_source.write_bytes(b"\x02" * 80)
    dest = lib / "Moved" / "chapter01.mp3"
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    return {
        "lib": lib,
        "src_dir": src_dir,
        "source": source,
        "alternate_source": alternate_source,
        "dest": dest,
        "quarantine": quarantine,
    }


def test_move_rejects_library_root_as_source(move_tree, audit_log):
    with pytest.raises(PathJailError):
        fs_move(
            str(move_tree["lib"]),
            str(move_tree["dest"]),
            [str(move_tree["lib"])],
            audit_log,
            confirm=True,
        )


def test_quarantine_rejects_library_root_as_source(move_tree, audit_log):
    with pytest.raises(PathJailError):
        fs_quarantine(
            str(move_tree["lib"]),
            [str(move_tree["lib"])],
            str(move_tree["quarantine"]),
            audit_log,
            confirm=True,
        )


def test_move_revalidates_source_before_mutation(move_tree, audit_log, monkeypatch):
    link = move_tree["lib"] / "current.mp3"
    link.symlink_to(move_tree["source"])

    original_mkdir = Path.mkdir
    swapped = False

    def swapping_mkdir(self, *args, **kwargs):
        nonlocal swapped
        result = original_mkdir(self, *args, **kwargs)
        if self == move_tree["dest"].parent and not swapped:
            link.unlink()
            link.symlink_to(move_tree["alternate_source"])
            swapped = True
        return result

    monkeypatch.setattr(Path, "mkdir", swapping_mkdir)

    with pytest.raises(PathJailError, match="changed after validation"):
        fs_move(
            str(link),
            str(move_tree["dest"]),
            [str(move_tree["lib"])],
            audit_log,
            confirm=True,
        )

    assert link.resolve() == move_tree["alternate_source"].resolve()
    assert not move_tree["dest"].exists()


def test_quarantine_revalidates_source_before_mutation(move_tree, audit_log, monkeypatch):
    link = move_tree["lib"] / "current.mp3"
    link.symlink_to(move_tree["source"])

    original_mkdir = Path.mkdir
    swapped = False

    def swapping_mkdir(self, *args, **kwargs):
        nonlocal swapped
        result = original_mkdir(self, *args, **kwargs)
        expected_parent = (
            move_tree["quarantine"] / move_tree["source"].relative_to(move_tree["lib"]).parent
        )
        if self == expected_parent and not swapped:
            link.unlink()
            link.symlink_to(move_tree["alternate_source"])
            swapped = True
        return result

    monkeypatch.setattr(Path, "mkdir", swapping_mkdir)

    with pytest.raises(PathJailError, match="changed after validation"):
        fs_quarantine(
            str(link),
            [str(move_tree["lib"])],
            str(move_tree["quarantine"]),
            audit_log,
            confirm=True,
        )

    quarantined = move_tree["quarantine"] / move_tree["source"].relative_to(move_tree["lib"])
    assert link.resolve() == move_tree["alternate_source"].resolve()
    assert not quarantined.exists()
