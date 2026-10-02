# Changelog

## [Unreleased]

### Fixed
- `batch_update_metadata` now keeps its series cache per library, refreshes it after
  series updates so newly created series are reused, and invalidates stale cache
  entries instead of sharing one process-wide series map across all libraries (#19).
- Added the missing `abs_librarian.__main__.main()` console entry point so the
  installed `abs-librarian-mcp` command now starts uvicorn with the same host,
  port, and empty-`MCP_TOKEN` startup guard as `python -m abs_librarian` (#23).

## [0.3.0] - 2026-10-03

### Upgrade notes
- Set a non-empty `MCP_TOKEN` before starting the server and configure clients to
  send it using the HTTP Authorization header with the Bearer scheme. Previous
  versions did not enforce this token; unauthenticated MCP access now fails.
  The `/health` endpoint remains public.
- For LAN or reverse-proxy access, explicitly configure `MCP_ALLOWED_HOSTS` with
  the trusted hostnames or IP addresses and externally visible ports used by
  clients (for example, `192.168.1.100:8000,nas.example:8000`).
  Arbitrary Host-header rewriting is removed; untrusted hosts are rejected.
  Keep SDK Origin validation enabled and follow the installation guide.
- This minor release changes deployment requirements for existing installations.

### Fixed
- Removed blanket Host-header rewriting. MCP v1 SDK transport security now
  validates exact trusted hosts, with explicit LAN opt-in via `MCP_ALLOWED_HOSTS`.
  Localhost health checks and SDK Origin validation are preserved.
- Constrained Python and Docker dependencies to the compatible MCP v1 SDK
  (`mcp[cli]>=1.12,<2`), including the transport-security API requirement (#1, #5).
- Made `/health` report the canonical package version in installed-package and
  source-only Docker deployments. Hatch reads the same version source (#3).

### Security
- MCP authentication is now actually enforced. Previously `MCP_TOKEN` was only copied into an
  unused `MCP_AUTH_TOKEN` environment variable, so every tool was reachable without credentials.
  All MCP HTTP requests now require `Authorization: Bearer <MCP_TOKEN>` (constant-time
  comparison) and are rejected with HTTP 401 otherwise; `/health` stays public.
- Fail closed: the server refuses to start when `MCP_TOKEN` is empty, and the auth layer rejects
  every MCP request (HTTP 503) if it is ever constructed without a token.
- Validated all Audiobookshelf item and library IDs before HTTP requests and
  encoded accepted path IDs as single segments. Batch validation prevents partial
  updates when an invalid ID occurs in a later chunk (#6).

### Added
- Defined a `dev` extra containing pytest, pytest-asyncio, and Ruff; aligned CI and
  developer installation instructions with the declared dependencies (#2).
- Added an independent Docker image build to CI for main pushes and pull requests,
  without publishing images or requiring registry credentials (#7).
- Added regression coverage for dependency compatibility, version reporting,
  authentication, trusted Hosts and Origins, and API identifier validation.

## [0.2.11] - 2026-06-12

### Added
- `delete_item` tool: delete a single ABS item record by ID (dry-run by default, requires confirm=True)

## [0.2.10] - 2026-06-12

### Fixed
- `list_missing` and `purge_missing`: ABS filter API for `issues.missing` does not work reliably.
  Replaced with client-side filtering: fetch all items and filter by `isMissing` flag, which is
  the same approach used by `library_overview` (confirmed accurate).

## [0.2.9] - 2026-06-12

### Fixed
- `library_overview` series count now derived from `seriesName` strings on items (same as
  authors), replacing the broken `get_series()` endpoint call which returned 0 results.
  Series names are deduplicated by stripping the sequence suffix (e.g. "Series #3" → "Series").

## [0.2.8] - 2026-06-12

### Fixed
- `list_missing` and `purge_missing`: ABS filter format is `{group}.{base64(value)}` not
  `base64("{group}.{value}")` — fixed to `"issues." + base64("missing")`

## [0.2.7] - 2026-06-12

### Fixed
- `library_overview` and `find_items` now correctly read authors and series from the ABS list
  endpoint, which returns minified metadata using `authorName`/`seriesName` strings rather than
  `authors`/`series` arrays (those are only in the expanded single-item response)
- `library_overview` series count now uses the dedicated `/api/libraries/{id}/series` endpoint
- Removed ineffective `include=authors,series` parameter that was not a valid ABS API option

## [0.2.6] - 2026-06-12

### Fixed
- `set_cover` no longer crashes when ABS search_covers returns a list of URL strings instead of dicts

## [0.2.5] - 2026-06-12

### Fixed
- `scan_library` and `quick_match` no longer crash on non-JSON ABS responses (all HTTP methods now use try/except around `.json()`)
- `tool_fs_move` and `tool_fs_quarantine` no longer crash with duplicate `dry_run` kwarg in `log_operation` call
- `tool_fs_tree` no longer returns oversized responses — audio file lists suppressed at all depths (counts still shown)

## [0.2.4] - 2026-06-12

### Fixed
- `list_missing` and `purge_missing` now correctly filter missing items by base64-encoding the ABS filter parameter (`issues.missing`)

## [0.2.3] - 2026-06-12

### Fixed
- `find_items` and `library_overview` now return authors and series correctly by passing `include=authors,series` to the ABS library items endpoint

## Initial release

### Added
- All v1 tools from the project brief
- ABS API tools: `library_overview`, `find_items`, `get_item`, `batch_update_metadata`, `quick_match`, `set_cover`, `scan_library`, `list_missing`, `purge_missing`, `create_backup`
- File-system tools: `fs_tree`, `detect_blobs`, `fs_make_book_folders`, `fs_flatten`, `fs_move`, `fs_quarantine`
- Path jail, audit log, dry-run-by-default safety model
- Docker image with GHCR CI/CD; Unraid community-apps template
