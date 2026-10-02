# Audiobookshelf Librarian MCP

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant fully manage a self-hosted [Audiobookshelf](https://www.audiobookshelf.org/) library — including the file-system fixes the ABS API cannot do.

## Features

| Category | Tools |
|---|---|
| **Library info** | `library_overview`, `find_items`, `get_item` |
| **Metadata** | `batch_update_metadata`, `quick_match`, `set_cover` |
| **Maintenance** | `scan_library`, `list_missing`, `purge_missing`, `create_backup` |
| **File system** | `fs_tree`, `detect_blobs`, `fs_make_book_folders`, `fs_flatten`, `fs_move`, `fs_quarantine` |

### What makes this different

Existing ABS MCPs only wrap the read/manage API. This server also ships **file-system tools**:

- **`fs_make_book_folders`** — splits "blob" folders (many books scanned as one) by moving each audio file into its own named subfolder.
- **`fs_flatten`** — merges per-disc/CD/part subfolders up into the parent with prefixed filenames.
- **`fs_quarantine`** — moves duplicates or unwanted files to a quarantine folder. Nothing is ever deleted.

## Safety model

- **Move-only / no delete**: quarantine instead of delete everywhere.
- **Dry-run by default**: every file tool returns a plan unless you pass `confirm=true`.
- **Path jail**: all paths are validated against configured library roots; `..` traversal, symlinks that exit the jail, and absolute paths outside roots are rejected and logged.
- **Audit log**: every file operation is appended to a JSON-lines file inside your library mount.
- **Dedicated ABS token**: never your login credentials.
- **DNS rebinding protection**: MCP requests retain their original Host header and must match an explicit trusted-host allowlist. SDK Origin checks remain enabled.
- **ABS ID validation**: item and library IDs must be non-empty raw IDs, not URL-encoded
  values. UUID and legacy IDs are supported without requiring a specific format.
  Dot segments (`.` / `..`), `/`, `\`, `%`, `?`, `#`, and control characters raise
  `ValueError` before an API request. Accepted IDs are URL-encoded as a single path
  segment; batch IDs are validated but remain unchanged in JSON bodies.

## Quick start

> **New here?** See [INSTALLATION.md](INSTALLATION.md) for the full walkthrough — including the **Claude-assisted install**, where you hand Claude this repo and it deploys and wires up the connector for you.

### docker run

```bash
docker run -d \
  --name abs-librarian-mcp \
  -p 8000:8000 \
  -v /mnt/user/audiobooks:/audiobooks:rw \
  -v /mnt/user/quarantine:/quarantine:rw \
  -e ABS_URL=http://192.168.1.100:13378 \
  -e ABS_TOKEN=your-abs-token \
  -e LIBRARY_ROOTS=/audiobooks \
  -e QUARANTINE_DIR=/quarantine \
  -e MCP_TOKEN=your-long-random-secret \
  -e MCP_ALLOWED_HOSTS=192.168.1.100:8000 \
  ghcr.io/rhamblen/audiobookshelf-librarian-mcp:latest
```

### docker compose

Copy `.env.example` to `.env`, fill in your values, then:

```bash
docker compose up -d
```

### Unraid

Import `abs-librarian-mcp.xml` via Community Applications → "Add Container from XML", or add the GitHub URL to your template repositories.

## Claude connector setup

In Claude Desktop (`claude_desktop_config.json`) or the Claude web app (Settings → Connectors):

```json
{
  "mcpServers": {
    "abs-librarian": {
      "url": "http://YOUR-SERVER-IP:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_TOKEN"
      }
    }
  }
}
```

Replace `YOUR-SERVER-IP` and `YOUR_MCP_TOKEN` with your values.
Set `MCP_ALLOWED_HOSTS` to the exact server address and port in the connector URL;
the example above assumes the MCP server itself is at `192.168.1.100`.

## Configuration (environment variables)

| Variable | Required | Default | Description |
|---|---|---|---|
| `ABS_URL` | ✅ | — | Audiobookshelf base URL |
| `ABS_TOKEN` | ✅ | — | ABS API token |
| `LIBRARY_ROOTS` | ✅ | — | Colon-separated container paths for the library |
| `QUARANTINE_DIR` | ✅ | `/quarantine` | Where unwanted files are moved |
| `MCP_TOKEN` | ✅ | — | Static bearer token required on every `/mcp` request (`Authorization: Bearer <token>`); the server refuses to start without it. Only `/health` is public. |
| `DRY_RUN_DEFAULT` | — | `true` | File tools default to dry-run |
| `PORT` | — | `8000` | Server listen port |
| `MCP_ALLOWED_HOSTS` | — | empty (loopback only) | Additional comma-separated exact Host values, e.g. `192.168.1.100:8000,librarian.lan:8000`; no wildcards, URLs, or paths |
| `AUDIT_LOG` | — | `/audiobooks/.abs-librarian-audit.jsonl` | Audit log path |
| `BLOB_HOURS_THRESHOLD` | — | `6.0` | `detect_blobs` hours threshold (overridable per-call) |
| `BLOB_FILE_COUNT_THRESHOLD` | — | `10` | `detect_blobs` file-count threshold (overridable per-call) |

### Trusted hosts for LAN deployment

By default, `/mcp` trusts only `localhost`, `127.0.0.1`, and `[::1]`, either bare
or with the configured `PORT`. For LAN clients, explicitly add the **server's**
IP or hostname and the externally visible port to `MCP_ALLOWED_HOSTS`. For
example, a Docker mapping `9000:8000` needs `192.168.1.100:9000`, not the container
port. Bare entries allow only a Host header without a port; IPv6 must be bracketed.
Entries match exactly; wildcards are rejected at startup. Restart after changes.

Reverse proxies must forward an explicitly trusted Host value; do not normalize
arbitrary incoming hosts to localhost. Trust only server names you control.
This allowlist is not authentication or a firewall: keep access on a trusted
network. Requests without an Origin header (typical non-browser MCP clients) can
use explicitly trusted LAN hosts. A supplied Origin still must match the SDK's
localhost HTTP Origin policy; adding a LAN Host does **not** trust browser origins.
Untrusted Hosts return HTTP 421; untrusted Origins return HTTP 403.
The standalone `/health` route remains available for localhost container checks
and is not an MCP endpoint.

## Tool reference

### `library_overview`
Returns counts per library: items, authors, series, no-cover, no-series, missing.

### `find_items(library_id, ...)`
Filtered search. Filters: `title_regex`, `author`, `series`, `no_cover`, `no_series`, `missing`, `min/max_duration_hours`, `min/max_file_count`. Returns compact results (limit 200 default).

### `get_item(item_id)`
Full detail for one item including file list.

### `batch_update_metadata(library_id, updates)`
Bulk metadata update. Each update: `{id, title?, authors?, narrators?, series?, genres?, tags?}`. Series names are auto-resolved to existing series IDs to avoid duplicates.

### `quick_match(item_ids, provider?, override_cover?, override_details?)`
Batch quick-match against Audible (default) or another provider.

### `set_cover(item_id, url? | search_title?, search_author?, provider?)`
Set a cover from a URL or from a provider cover search.

### `scan_library(library_id)`
Trigger an ABS library scan.

### `list_missing(library_id)` / `purge_missing(library_id, confirm?)`
List or delete ABS records for missing items (files already gone; does not touch disk).

### `create_backup()`
Trigger an ABS backup.

### `fs_tree(path, max_depth?)`
Folder tree with audio-file counts and sizes (depth-limited, default 3).

### `detect_blobs(path, hours_threshold?, file_count_threshold?)`
Heuristic scan: flags items above the hour or file-count threshold and notes which have disc subfolders.

### `fs_make_book_folders(path, confirm?)`
Splits a blob folder: each loose audio file → own named subfolder. Dry-run unless `confirm=true`.

### `fs_flatten(path, confirm?)`
Merges disc/CD/part subfolders into the parent with prefixed filenames. Dry-run unless `confirm=true`.

### `fs_move(src, dest, confirm?)`
Moves a file or folder within the library. No overwrite. Dry-run unless `confirm=true`.

### `fs_quarantine(path, confirm?)`
Moves a file or folder to quarantine, preserving relative structure. Dry-run unless `confirm=true`.

## Example prompts

```
Show me a library overview.

Find all items with no series assigned in library lib_abc123.

Batch-update genres for these 50 items to ["Science Fiction"]: [...]

Show me the folder tree at /audiobooks/Author Name — depth 2.

Detect blobs under /audiobooks with more than 8 hours estimated runtime.

Split the blob at /audiobooks/Author Name/Big Omnibus — dry run first, then confirm.

Flatten the disc folders in /audiobooks/Author Name/Series Book 1 — dry run.

Quarantine /audiobooks/Author Name/Series Book 1 (mp3 copy) — confirm.
```

## Development

The package version is defined only in `src/abs_librarian/__init__.py`.
Hatch reads this value to generate distribution metadata, and `/health` reports
the same value for both installed packages and source-only Docker deployments.
Update `__version__` when releasing a new version; no runtime metadata lookup or
fallback version is needed.

Python and Docker installations require `mcp[cli]>=1.12,<2` because the server uses the
v1 `mcp.server.fastmcp.FastMCP` API. Keep this upper bound until the server is migrated
to the MCP v2 API.

The `dev` extra installs pytest, pytest-asyncio, and Ruff, matching the CI setup.

```bash
git clone https://github.com/rhamblen/Audiobookshelf-librarian-MCP
cd Audiobookshelf-librarian-MCP
python -m pip install -e ".[dev]"
cp .env.example .env   # fill in your values
python -m abs_librarian

# Tests
pytest

# Lint
ruff check src/ tests/
```

## License

MIT © Richard Hamblen
