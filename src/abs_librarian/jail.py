"""Path-jail enforcement — security-critical module.

Every file path used by fs_* tools must pass through resolve_safe() before use.
Rules:
  - Must resolve to a real path (no traversal via ..)
  - Must not be or pass through a symlink that exits the jail
  - Must sit under at least one configured library root OR the quarantine dir

Mutating tools perform an additional same-target revalidation immediately before
filesystem changes. This narrows, but cannot fully eliminate, final TOCTOU races
while Python still relies on high-level path-based APIs instead of dirfd/openat
primitives.
"""

from __future__ import annotations

from pathlib import Path


class PathJailError(ValueError):
    """Raised when a path falls outside all permitted roots."""


def resolve_safe(raw: str, permitted_roots: list[str]) -> Path:
    """Return the resolved absolute Path of *raw* if it is inside a permitted root.

    Raises PathJailError otherwise.  Never follows symlinks outside the jail.
    """
    try:
        # strict=False so the path need not exist yet (e.g. destination of a move)
        candidate = Path(raw).resolve(strict=False)
    except (OSError, ValueError) as exc:
        raise PathJailError(f"Cannot resolve path {raw!r}: {exc}") from exc

    # Reject if any existing prefix is a symlink pointing outside a root
    _check_no_escaping_symlinks(candidate, permitted_roots)

    for root in permitted_roots:
        try:
            resolved_root = Path(root).resolve(strict=False)
        except (OSError, ValueError):
            continue
        try:
            candidate.relative_to(resolved_root)
            return candidate
        except ValueError:
            continue

    raise PathJailError(
        f"Path {raw!r} (resolved: {candidate}) is outside all permitted roots: {permitted_roots}"
    )


def resolve_mutation_source(raw: str, permitted_roots: list[str]) -> Path:
    """Resolve a mutation source and reject the jail root itself."""
    candidate = resolve_safe(raw, permitted_roots)
    for root in _resolved_roots(permitted_roots):
        if candidate == root:
            raise PathJailError(f"Path {raw!r} resolves to jail root {root} and cannot be mutated")
    return candidate


def revalidate_resolved(
    raw: str,
    permitted_roots: list[str],
    expected: Path,
    *,
    path_label: str = "path",
    reject_root: bool = False,
) -> Path:
    """Re-resolve *raw* and require the same safe target as the earlier check."""
    current = (
        resolve_mutation_source(raw, permitted_roots)
        if reject_root
        else resolve_safe(raw, permitted_roots)
    )
    if current != expected:
        raise PathJailError(
            f"{path_label.capitalize()} {raw!r} changed after validation "
            f"(expected {expected}, now {current})"
        )
    return current


def _check_no_escaping_symlinks(path: Path, permitted_roots: list[str]) -> None:
    """Walk path components; if any existing part is a symlink, verify it resolves inside a root."""
    parts = list(path.parts)
    for i in range(1, len(parts) + 1):
        partial = Path(*parts[:i])
        if partial.is_symlink():
            real = partial.resolve(strict=False)
            inside = any(
                _is_inside(real, Path(r).resolve(strict=False)) for r in permitted_roots
            )
            if not inside:
                raise PathJailError(
                    f"Symlink {partial} points outside permitted roots (resolves to {real})"
                )


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolved_roots(permitted_roots: list[str]) -> list[Path]:
    roots: list[Path] = []
    for root in permitted_roots:
        try:
            roots.append(Path(root).resolve(strict=False))
        except (OSError, ValueError):
            continue
    return roots
