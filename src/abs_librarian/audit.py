"""Append-only JSON-lines audit log for every file operation."""

from __future__ import annotations

import json
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_lock = threading.Lock()


class AuditLogError(RuntimeError):
    """Raised when an audit entry cannot be written."""


def log_operation(
    audit_log_path: str,
    operation: str,
    dry_run: bool,
    **kwargs: Any,
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "op": operation,
        "dry_run": dry_run,
        **kwargs,
    }
    path = Path(audit_log_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        message = (
            f"CRITICAL: failed to write audit log for {operation} to {path}: {exc}"
        )
        if not dry_run:
            message += " Operation aborted before mutating the filesystem."
        print(message, file=sys.stderr)
        raise AuditLogError(message) from exc
