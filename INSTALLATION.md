# Installation Guide

This guide covers installing the **Audiobookshelf Librarian MCP** server and connecting it to Claude.

There are two paths:

- **[Option A — Claude-assisted (recommended)](#option-a--claude-assisted-recommended)** — hand the repo to Claude and let it deploy and wire everything up for you.
- **[Option B — Manual install](#option-b--manual-install)** — do it yourself with Docker, Docker Compose, or the Unraid template.

Either way, you'll end with the server running as a container and Claude connected to it as an MCP connector.

---

## Before you start

You'll need three things regardless of which path you choose:

1. **A host that runs Docker** — a NAS (Unraid, Synology), a home server, or any Linux box. It must be able to reach your Audiobookshelf instance and mount the same library files Audiobookshelf uses.
2. **An Audiobookshelf API token** — in Audiobookshelf go to **Settings → Users → (your user) → API Token** and copy it. Use a dedicated user, never your admin login.
3. **A long random `MCP_TOKEN`** — this is the bearer token Claude presents to authenticate to the server. Generate one, for example:

   ```bash
   openssl rand -hex 32
   ```

> **Important — use TLS for connector traffic.** The application itself speaks
> plain HTTP, so `MCP_TOKEN` is sent in cleartext unless you put the service
> behind an HTTPS reverse proxy. For anything beyond a fully trusted LAN
> segment, terminate TLS in Caddy, nginx, Traefik, or a similar reverse proxy.

> **Important — paths must match.** The path you mount as `/audiobooks` in this container must point at the *same files* Audiobookshelf sees as its library. If Audiobookshelf reads `/mnt/user/audiobooks`, mount that same host path here. Otherwise the file-system tools won't find your books.

---

## Option A — Claude-assisted (recommended)

You don't have to read Docker docs or hand-edit config files. Point Claude at this repository and let it do the work.

### 1. Open Claude with access to your server

Use **Claude Code** in a terminal on (or with SSH/MCP access to) the machine that will run the container. If your server is an Unraid box and you have the Unraid MCP connected, Claude can deploy the container directly through it.

### 2. Give Claude this repository and your details

Paste a prompt like the one below, filling in your own values:

```
Please install the Audiobookshelf Librarian MCP server for me.

Repo: https://github.com/schmidt-software/Audiobookshelf-librarian-MCP

My setup:
- Audiobookshelf URL: http://192.168.1.100:13378
- Audiobookshelf API token: <paste your ABS_TOKEN>
- MCP server LAN address and mapped port: 192.168.1.100:8000
- Audiobook library path on this host: /mnt/user/audiobooks
- Where to put quarantined files: /mnt/user/quarantine

Read the repo's README and docker-compose.yml, then:
1. Generate a strong MCP_TOKEN for me.
2. Deploy the ghcr.io/schmidt-software/audiobookshelf-librarian-mcp:latest container
   with the correct volume mounts and environment variables. Set MCP_ALLOWED_HOSTS
   to my exact MCP server LAN address and mapped port; do not use wildcards
   or disable the SDK Host/Origin checks.
3. Verify it's healthy by hitting the /health endpoint.
4. Give me the exact Claude connector config (URL + Authorization header)
   so I can add it to Claude Desktop / the web app.
```

### 3. Let Claude verify and hand you the connector config

Claude will read the repo, start the container, confirm `/health` returns `{"status": "ok", ...}`, and print the connector JSON for the final step. Then jump to **[Connect Claude to the server](#connect-claude-to-the-server)** below to paste it in.

If anything fails (wrong path, unreachable ABS, port already in use), tell Claude the error and it will adjust — that's the point of this path.

---

## Option B — Manual install

Pick **one** of the three methods below, then continue to **[Connect Claude to the server](#connect-claude-to-the-server)**.

### Method 1 — `docker run`

```bash
docker run -d \
  --name abs-librarian-mcp \
  --restart unless-stopped \
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

### Method 2 — Docker Compose

1. Clone the repo (or just copy `docker-compose.yml` and `.env.example`):

   ```bash
   git clone https://github.com/schmidt-software/Audiobookshelf-librarian-MCP
   cd Audiobookshelf-librarian-MCP
   ```

2. Create your env file and fill in the values:

   ```bash
   cp .env.example .env
   # then edit .env — set ABS_URL, ABS_TOKEN, MCP_TOKEN, MCP_ALLOWED_HOSTS, and the paths
   ```

3. Confirm the volume paths in `docker-compose.yml` match your host (the `/mnt/user/...` lines), then start it:

   ```bash
   docker compose up -d
   ```

### Recommended — put the container behind an HTTPS reverse proxy

The container does not provide TLS itself. Keep it bound to a local interface or
trusted LAN, and let a reverse proxy handle certificates and HTTPS.

1. Pick a hostname clients will use, for example `abs-librarian.example.com`.
2. Set `MCP_ALLOWED_HOSTS` to that exact hostname (or hostname plus mapped port,
   if you terminate TLS on a non-default port).
3. Configure the proxy to forward the original Host header unchanged.
4. Point Claude at `https://abs-librarian.example.com/mcp`.

Example Caddyfile:

```caddy
abs-librarian.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Example nginx config:

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

If you keep the server on plain HTTP for local-only use, treat that network as
trusted: the bearer token is otherwise visible to anyone who can capture traffic.

### Method 3 — Unraid

1. In Unraid, go to **Docker → Add Container**, then **Add Container from XML** (Community Applications), and import [`abs-librarian-mcp.xml`](abs-librarian-mcp.xml) from this repo — or add the repository's GitHub URL to your template repositories.
2. Fill in the template fields:
   - **Port** — host port for the server (defaults to `8000`; remember whichever you pick for the connector URL).
   - **ABS_URL** — your Audiobookshelf LAN address.
   - **ABS_TOKEN** — your Audiobookshelf API token.
   - **MCP_TOKEN** — your generated bearer token.
   - **MCP_ALLOWED_HOSTS** — your MCP server's exact LAN address and mapped host port (for example `192.168.1.100:8000`); not the Audiobookshelf address or client IP.
   - **Audiobooks Path** — the host path of your library (must match what Audiobookshelf uses).
   - **Quarantine Path** — where unwanted files get moved.
3. Apply to pull the image and start the container.

---

## Connect Claude to the server

Once the container is running, add it as a connector in **Claude Desktop** (`claude_desktop_config.json`) or the **Claude web app** (Settings → Connectors):

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

When you use a reverse proxy, prefer an HTTPS connector URL such as
`https://abs-librarian.example.com/mcp`.

- Replace `YOUR-SERVER-IP` with your server's LAN IP.
- Replace `8000` with the host port you mapped, if you changed it.
- Replace `YOUR_MCP_TOKEN` with the `MCP_TOKEN` you set.
- Add `YOUR-SERVER-IP:8000` (using your mapped port) to `MCP_ALLOWED_HOSTS` and restart the container. The `docker run` example assumes the MCP server is at `192.168.1.100`.

Only loopback Hosts are trusted by default. For LAN deployment, use exact
comma-separated server Host values such as `192.168.1.100:9000,librarian.lan:9000`
for a `9000:8000` port mapping. No schemes, paths, or wildcards are accepted.
IPv6 values must be bracketed (for example `[fd00::1]:8000`). Reverse proxies must
forward a trusted Host, not rewrite arbitrary incoming Hosts to localhost.
The allowlist does not replace authentication or network access restrictions.
Origin checks remain the SDK's localhost HTTP policy: non-browser clients can
omit Origin, but adding a LAN Host does not authorize a browser's LAN Origin.
See [Trusted hosts for LAN deployment](README.md#trusted-hosts-for-lan-deployment).

Restart Claude Desktop (or reload the connector in the web app) and the `abs-librarian` tools will appear.

---

## Verify it's working

1. **Health check** — visit `http://YOUR-SERVER-IP:8000/health` in a browser, or:

   ```bash
   curl http://YOUR-SERVER-IP:8000/health
   ```

   A healthy server returns something like `{"status": "ok", "abs_libraries": 2}`. If you see `{"status": "error", ...}`, the server is up but can't reach Audiobookshelf — check `ABS_URL` and `ABS_TOKEN`.

2. **Ask Claude** — once the connector is added, try:

   ```
   Show me a library overview.
   ```

   You should get per-library counts back.

> **Safety reminder.** Mutating tools use `DRY_RUN_DEFAULT` when `dry_run` is omitted,
> so the default behavior is still a dry run unless you explicitly set
> `DRY_RUN_DEFAULT=false` or pass `dry_run=false`. `confirm=true` remains accepted as a
> compatibility alias for execution. Nothing is ever deleted from disk; unwanted files
> are *moved* to the quarantine folder. All operations are appended to the audit log
> inside your library mount.

---

## Configuration reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `ABS_URL` | ✅ | — | Audiobookshelf base URL |
| `ABS_TOKEN` | ✅ | — | ABS API token |
| `LIBRARY_ROOTS` | ✅ | — | Colon-separated container paths for the library |
| `ABS_LIBRARY_ITEMS_LIMIT` | — | `5000` | Maximum number of items requested per library listing call |
| `QUARANTINE_DIR` | ✅ | `/quarantine` | Where unwanted files are moved |
| `MCP_TOKEN` | ✅ | — | Static bearer token required on every `/mcp` request (`Authorization: Bearer <token>`); the server refuses to start without it. Only `/health` is public. |
| `MCP_AUTH_FAILURE_LIMIT` | — | `5` | Failed auth attempts allowed per client IP inside the rolling window before HTTP 429 backoff starts |
| `MCP_AUTH_FAILURE_WINDOW_SECONDS` | — | `300` | Rolling window for counting failed auth attempts per client IP |
| `MCP_AUTH_BACKOFF_SECONDS` | — | `60` | Initial `Retry-After` backoff, doubled on repeated failures inside the window |
| `MCP_AUTH_MAX_BACKOFF_SECONDS` | — | `900` | Maximum `Retry-After` backoff for repeated failed auth attempts |
| `DRY_RUN_DEFAULT` | — | `true` | Default `dry_run` value for mutating tools when omitted |
| `PORT` | — | `8000` | Server listen port |
| `MCP_ALLOWED_HOSTS` | — | empty (loopback only) | Additional comma-separated exact server Host values, including mapped port; no wildcards, URLs, or paths |
| `AUDIT_LOG` | — | `/audiobooks/.abs-librarian-audit.jsonl` | Audit log path |
| `BLOB_HOURS_THRESHOLD` | — | `6.0` | `detect_blobs` hours threshold (overridable per-call) |
| `BLOB_FILE_COUNT_THRESHOLD` | — | `10` | `detect_blobs` file-count threshold (overridable per-call) |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/mcp` returns 421 | Untrusted Host | Add the exact server IP/hostname and externally mapped port to `MCP_ALLOWED_HOSTS`, then restart |
| `/mcp` returns 403 | Untrusted Origin | Adding a Host does not relax SDK Origin checks; use a non-browser MCP client without an Origin header |
| `/mcp` returns 429 | Too many failed auth attempts from one client IP | Wait for the `Retry-After` interval or adjust the auth backoff settings for your deployment |
| `/health` returns `{"status": "error"}` | Server can't reach Audiobookshelf | Check `ABS_URL` is reachable from the container and `ABS_TOKEN` is valid |
| Claude shows no tools / 401 | Token mismatch | Ensure the `Authorization: Bearer` value exactly equals `MCP_TOKEN` |
| Container exits with `MCP_TOKEN must be set` | `MCP_TOKEN` is empty | Set `MCP_TOKEN` to a long random secret; the server will not run unauthenticated |
| File tools say a path is rejected | Path jail | The path must live under `LIBRARY_ROOTS`; no `..`, symlinks out of the jail, or outside paths |
| File tools run but find nothing | Mount mismatch | The host path mounted as `/audiobooks` must be the same files Audiobookshelf indexes |
| Connector can't connect | Wrong port | Use the **host** port you actually mapped (the default is `8000`) |

---

## Developer setup

To run from source instead of the container:

Install the `dev` extra to include pytest, pytest-asyncio, and Ruff, as used in CI.

```bash
git clone https://github.com/schmidt-software/Audiobookshelf-librarian-MCP
cd Audiobookshelf-librarian-MCP
python -m pip install -e ".[dev]"
cp .env.example .env   # fill in your values
python -m abs_librarian

# Run tests
pytest

# Lint
ruff check src/ tests/
```
