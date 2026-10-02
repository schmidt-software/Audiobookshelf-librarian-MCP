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
- **Dry-run by default**: mutating tools honor `DRY_RUN_DEFAULT` (true by default) unless you
  pass `dry_run=false`.
- **Path jail**: all paths are validated against configured library roots; `..` traversal, symlinks that exit the jail, and absolute paths outside roots are rejected and logged.
- **Audit log**: every file operation is appended to a JSON-lines file inside your library mount.
- **Dedicated ABS token**: never your login credentials.
- **TLS at the edge**: terminate HTTPS in a reverse proxy; the built-in server speaks
  plain HTTP only, so do not send `MCP_TOKEN` over an untrusted network without TLS.
- **DNS rebinding protection**: MCP requests retain their original Host header and must match an explicit trusted-host allowlist. SDK Origin checks remain enabled.
- **ABS ID validation**: item and library IDs must be non-empty raw IDs, not URL-encoded
  values. UUID and legacy IDs are supported without requiring a specific format.
  Dot segments (`.` / `..`), `/`, `\`, `%`, `?`, `#`, and control characters raise
  `ValueError` before an API request. Accepted IDs are URL-encoded as a single path
  segment; batch IDs are validated but remain unchanged in JSON bodies.
- **Bounded title regexes**: `find_items.title_regex` rejects invalid or overly complex
  patterns, caps regex length, and matches only against the first 1024 characters of
  a title to reduce ReDoS risk.
- **Bounded library loading**: library item fetches no longer request unlimited results.
  They are capped by `ABS_LIBRARY_ITEMS_LIMIT` (default `5000`) to avoid loading an
  entire library in one call.

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
  ghcr.io/schmidt-software/audiobookshelf-librarian-mcp:latest
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
| `ABS_LIBRARY_ITEMS_LIMIT` | — | `5000` | Maximum number of items requested per library listing call |
| `LIBRARY_ROOTS` | ✅ | — | Colon-separated container paths for the library |
| `QUARANTINE_DIR` | ✅ | `/quarantine` | Where unwanted files are moved |
| `MCP_TOKEN` | ✅ | — | Static bearer token required on every `/mcp` request (`Authorization: Bearer <token>`); the server refuses to start without it. Only `/health` is public. |
| `MCP_AUTH_FAILURE_LIMIT` | — | `5` | Failed auth attempts allowed per client IP inside the rolling window before HTTP 429 backoff starts |
| `MCP_AUTH_FAILURE_WINDOW_SECONDS` | — | `300` | Rolling window for counting failed auth attempts per client IP |
| `MCP_AUTH_BACKOFF_SECONDS` | — | `60` | Initial `Retry-After` backoff, doubled on repeated failures inside the window |
| `MCP_AUTH_MAX_BACKOFF_SECONDS` | — | `900` | Maximum `Retry-After` backoff for repeated failed auth attempts |
| `DRY_RUN_DEFAULT` | — | `true` | Default `dry_run` value for mutating tools when omitted |
| `PORT` | — | `8000` | Server listen port |
| `MCP_ALLOWED_HOSTS` | — | empty (loopback only) | Additional comma-separated exact Host values, e.g. `192.168.1.100:8000,librarian.lan:8000`; no wildcards, URLs, or paths |
| `COVER_URL_ALLOWED_HOSTS` | — | empty | Additional comma-separated exact hosts or IPs allowed for `set_cover` URLs even when they resolve to private, loopback, or link-local addresses |
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

### TLS reverse proxy (recommended)

The application does **not** implement TLS itself. If you expose it beyond a
trusted local network segment, put it behind an HTTPS reverse proxy so
`MCP_TOKEN` never travels in cleartext.

Set `MCP_ALLOWED_HOSTS` to the hostname clients will actually use through the
proxy, and have the proxy forward that same Host value to the app. Example
Caddyfile:

```caddy
abs-librarian.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Example nginx server block:

```nginx
server {
    listen 443 ssl http2;
    server_name abs-librarian.example.com;

    ssl_certificate /etc/letsencrypt/live/abs-librarian.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/abs-librarian.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

With either proxy, set `MCP_ALLOWED_HOSTS=abs-librarian.example.com` and point
Claude at `https://abs-librarian.example.com/mcp`.

## Tool reference

### `library_overview`
Returns counts per library: items, authors, series, no-cover, no-series, missing.

### `find_items(library_id, ...)`
Filtered search. Filters: `title_regex`, `author`, `series`, `no_cover`, `no_series`, `missing`, `min/max_duration_hours`, `min/max_file_count`. Invalid regexes return a clear error, overly long or complex patterns are rejected, and title matching is bounded to the first 1024 characters. Returns compact results (limit 200 default).

### `get_item(item_id)`
Full detail for one item including file list.

### `batch_update_metadata(library_id, updates)`
Bulk metadata update. Each update: `{id, title?, authors?, narrators?, series?, genres?, tags?}`. Series names are auto-resolved to existing series IDs to avoid duplicates.

### `quick_match(item_ids, provider?, override_cover?, override_details?)`
Batch quick-match against Audible (default) or another provider.

### `set_cover(item_id, url? | search_title?, search_author?, provider?)`
Set a cover from a URL or from a provider cover search. Direct and provider-returned
URLs must use HTTP or HTTPS and must not resolve to private, loopback, or link-local
addresses unless the host is explicitly allowlisted in `COVER_URL_ALLOWED_HOSTS`.

### `scan_library(library_id)`
Trigger an ABS library scan.

### `list_missing(library_id)` / `purge_missing(library_id, dry_run?)`
List or delete ABS records for missing items (files already gone; does not touch disk).
Omit `dry_run` to use `DRY_RUN_DEFAULT`; `confirm=true` remains accepted as a
compatibility alias for `dry_run=false`.

### `delete_item(item_id, dry_run?)`
Delete a single ABS item record. Omit `dry_run` to use `DRY_RUN_DEFAULT`; `confirm=true`
remains accepted as a compatibility alias for `dry_run=false`.

### `create_backup(dry_run?)`
Trigger an ABS backup. Omit `dry_run` to use `DRY_RUN_DEFAULT`; `confirm=true` remains
accepted as a compatibility alias for `dry_run=false`.

### `fs_tree(path, max_depth?)`
Folder tree with audio-file counts and sizes (depth-limited, default 3).

### `detect_blobs(path, hours_threshold?, file_count_threshold?)`
Heuristic scan: flags items above the hour or file-count threshold and notes which have disc subfolders.

### `fs_make_book_folders(path, dry_run?)`
Splits a blob folder: each loose audio file → own named subfolder. Omit `dry_run` to use
`DRY_RUN_DEFAULT`; `confirm=true` remains accepted as a compatibility alias for `dry_run=false`.

### `fs_flatten(path, dry_run?)`
Merges disc/CD/part subfolders into the parent with prefixed filenames. Omit `dry_run` to use
`DRY_RUN_DEFAULT`; `confirm=true` remains accepted as a compatibility alias for `dry_run=false`.

### `fs_move(src, dest, dry_run?)`
Moves a file or folder within the library. No overwrite. Omit `dry_run` to use
`DRY_RUN_DEFAULT`; `confirm=true` remains accepted as a compatibility alias for `dry_run=false`.

### `fs_quarantine(path, dry_run?)`
Moves a file or folder to quarantine, preserving relative structure. Omit `dry_run` to use
`DRY_RUN_DEFAULT`; `confirm=true` remains accepted as a compatibility alias for `dry_run=false`.

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
git clone https://github.com/schmidt-software/Audiobookshelf-librarian-MCP
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
