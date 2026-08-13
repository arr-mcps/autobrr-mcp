# autobrr-mcp

Part of the [arr-mcps](https://github.com/SavageCore/arr-mcps) collection.
MCP server exposing [autobrr](https://autobrr.com/)'s API as tools, so an LLM
can read and manage a full autobrr instance: filters, indexers, IRC networks,
RSS/Torznab feeds, download clients, actions, release queue and stats, import
lists, notifications, API keys, proxies, and system config.

Built with [FastMCP](https://gofastmcp.com). autobrr's API has no OpenAPI
spec, so the endpoint table is hand-maintained against autobrr's
`internal/http` handlers (see `AGENTS.md`).

## Creating an API key

Create a key in autobrr **Settings > API Keys**. The token is shown once at
creation; the server sends it as the `X-API-Token` header on every request.

## Install

Download a wheel from the [latest release](https://github.com/SavageCore/autobrr-mcp/releases/latest)
and install it as a `uv` tool (no repo checkout needed):

```bash
uv tool install autobrr_mcp-*.whl
```

This puts an `autobrr-mcp` command on your PATH. Register it with Claude Code:

```bash
claude mcp add autobrr \
  --env AUTOBRR_URL=https://autobrr.example.com \
  --env AUTOBRR_API_KEY=<key> \
  -- autobrr-mcp
```

### From source

```bash
uv sync
cp .env.example .env   # fill in AUTOBRR_URL and AUTOBRR_API_KEY
```

```bash
claude mcp add autobrr \
  --env AUTOBRR_URL=https://autobrr.example.com \
  --env AUTOBRR_API_KEY=<key> \
  -- uv run --directory /path/to/autobrr-mcp autobrr-mcp
```

## Config

| Env var | Required | Default |
|---|---|---|
| `AUTOBRR_URL` | yes | - |
| `AUTOBRR_API_KEY` | yes* | none (no auth header sent if unset) |

\* Every autobrr API endpoint requires a token; set it or every call returns
401. The server still starts without one so errors surface from the API rather
than at startup. If your autobrr instance is served under a base URL (e.g.
`https://host/autobrr/`), include that subpath in `AUTOBRR_URL`.

## Tools

Thirteen resource-scoped tools. Each takes an `operation` (one of the listed
endpoints) plus an `arguments` dict matching that operation's parameters, and
dispatches to the underlying endpoint. This is the fleet's portmanteau
pattern: ~104 autobrr endpoints wrapped as 13 tools so every session's
system prompt stays small.

| Tool | Operations (endpoints) |
|---|---|
| `autobrr_filters` | list, create, get, update, update_partial, delete, duplicate, toggle_enabled, get/update notifications (`/api/filters`, `/api/filters/{id}/...`) |
| `autobrr_indexers` | list, list_schemas, list_options, create, get, update, delete, test_api, toggle_enabled (`/api/indexer`) |
| `autobrr_irc` | list/create/get/update/delete networks, create channel, send_cmd, restart, message history, process announce (`/api/irc`) |
| `autobrr_feeds` | list, create, get, update, delete, delete_cache, test, fetch_caps, get_latest, force_run, toggle_enabled (`/api/feeds`) |
| `autobrr_download_clients` | list, create, update, test, get, delete, get_arr_tags (`/api/download_clients`) |
| `autobrr_actions` | list, create, update, delete, toggle_enabled (`/api/actions`) |
| `autobrr_lists` | list, create, update, delete, refresh_all, refresh_one (`/api/lists`) |
| `autobrr_notifications` | list, create, get, update, delete, test, get_pushover_sounds (`/api/notification`) |
| `autobrr_api_keys` | list, create, delete (`/api/keys`) |
| `autobrr_proxy` | list, create, get, update, delete, test (`/api/proxy`) |
| `autobrr_release` | list, recent, get, stats (+activity/volume/heatmap/top indexers/top filters), indexer options, delete, retry action, duplicate profiles, cleanup jobs CRUD/toggle/run (`/api/release`) |
| `autobrr_config` | get, update (`/api/config`) |
| `autobrr_system` | healthz liveness/readiness, log files, latest update, check updates (read-only) |

Excluded on purpose: `/api/auth` (session/OIDC, not usable over an API
token), `/api/events` (SSE stream), the inbound `/api/webhook` list-trigger
routes, and `/api/logs/files/{file}` (raw log download).

## Development

```bash
make help  # list all commands
```

| Command | Does |
|---|---|
| `make sync` | `uv sync` |
| `make test` | Offline tests - one per endpoint, mocked HTTP |
| `make test-integration` | Tests against the live instance (needs `AUTOBRR_URL`/`AUTOBRR_API_KEY`; write tests need `AUTOBRR_WRITE_TESTS=1`) |
| `make build` | Build wheel + sdist into `dist/` |
| `make bump-patch` / `bump-minor` / `bump-major` | Bump the version in `pyproject.toml` + `uv.lock` |
| `make clean` | Remove build artifacts |

The release workflow (`.github/workflows/release.yml`) builds and publishes to
[Releases](https://github.com/SavageCore/autobrr-mcp/releases) whenever a `v*`
tag is pushed - so the usual flow is `make bump-patch`, commit, then tag and
push.
