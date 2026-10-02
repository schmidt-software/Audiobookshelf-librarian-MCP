"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from ipaddress import IPv6Address

from .url_security import parse_cover_url_allowed_hosts


def _trusted_hosts(raw: str) -> list[str]:
    """Parse exact Host values; never pass wildcard patterns to the SDK."""
    if not raw.strip():
        return []
    hosts = [value.strip() for value in raw.split(",")]
    for host in hosts:
        match = re.fullmatch(
            r"(?P<host>\[[0-9a-fA-F:.]+\]|[a-zA-Z0-9][a-zA-Z0-9.-]*)"
            r"(?::(?P<port>[0-9]+))?",
            host,
        )
        if not match:
            raise ValueError("MCP_ALLOWED_HOSTS must contain exact hosts with optional ports")
        name = match.group("host")
        if name.startswith("["):
            IPv6Address(name[1:-1])
        if match.group("port") is not None and not 1 <= int(match.group("port")) <= 65535:
            raise ValueError("MCP_ALLOWED_HOSTS ports must be between 1 and 65535")
    return list(dict.fromkeys(hosts))


@dataclass
class Config:
    abs_url: str
    abs_token: str
    library_roots: list[str]
    quarantine_dir: str
    mcp_token: str
    dry_run_default: bool
    port: int
    audit_log: str
    # detect_blobs defaults (overridable per-call)
    blob_hours_threshold: float
    blob_file_count_threshold: int
    mcp_allowed_hosts: list[str] = field(default_factory=list)
    cover_url_allowed_hosts: list[str] = field(default_factory=list)

    @property
    def trusted_hosts(self) -> list[str]:
        loopback = ["localhost", "127.0.0.1", "[::1]"]
        return loopback + [f"{host}:{self.port}" for host in loopback] + self.mcp_allowed_hosts

    @classmethod
    def from_env(cls) -> Config:
        abs_url = os.environ["ABS_URL"].rstrip("/")
        abs_token = os.environ["ABS_TOKEN"]
        roots_raw = os.environ.get("LIBRARY_ROOTS", "")
        library_roots = [r for r in roots_raw.split(":") if r]
        quarantine_dir = os.environ.get("QUARANTINE_DIR", "/quarantine")
        mcp_token = os.environ.get("MCP_TOKEN", "")
        dry_run_default = (
            os.environ.get("DRY_RUN_DEFAULT", "true").lower() not in ("false", "0", "no")
        )
        port = int(os.environ.get("PORT", "8000"))
        audit_log = os.environ.get("AUDIT_LOG", "/audiobooks/.abs-librarian-audit.jsonl")
        blob_hours = float(os.environ.get("BLOB_HOURS_THRESHOLD", "6.0"))
        blob_files = int(os.environ.get("BLOB_FILE_COUNT_THRESHOLD", "10"))
        return cls(
            abs_url=abs_url,
            abs_token=abs_token,
            library_roots=library_roots,
            quarantine_dir=quarantine_dir,
            mcp_token=mcp_token,
            dry_run_default=dry_run_default,
            port=port,
            audit_log=audit_log,
            blob_hours_threshold=blob_hours,
            blob_file_count_threshold=blob_files,
            mcp_allowed_hosts=_trusted_hosts(os.environ.get("MCP_ALLOWED_HOSTS", "")),
            cover_url_allowed_hosts=parse_cover_url_allowed_hosts(
                os.environ.get("COVER_URL_ALLOWED_HOSTS", "")
            ),
        )
