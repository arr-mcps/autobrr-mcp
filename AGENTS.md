# AGENTS.md — autobrr-mcp

MCP server exposing autobrr's REST API (read + write) as tools so an LLM can read and manage a full autobrr instance: filters, indexers, IRC networks, RSS/Torznab feeds, download clients, actions, the release queue and its stats, import lists, notifications, API keys, proxies, config, health, and update checks. Uses FastMCP, `uv` for deps.

Exposed as **13 resource-scoped portmanteau tools**, not one tool per endpoint — see "Portmanteau registration" below. autobrr's API has no OpenAPI spec, so the endpoint table is hand-written from autobrr's Go source rather than generated from a vendored spec.

## Testing
- Offline suite: `make test` (or `uv run pytest`)
- Live integration (needs `AUTOBRR_URL`/`AUTOBRR_API_KEY`): `make test-integration`
  - GET endpoints run against the live instance.
  - POST/PUT/PATCH/DELETE only run when `AUTOBRR_WRITE_TESTS=1` (safe create→update→delete cycles against a scratch filter and a scratch API key, then cleanup). Never point write tests at a production instance you care about.

## Tool registry and the autobrr source
- `_TOOL_REGISTRY` in `autobrr_mcp.py` lists every JSON-producing autobrr endpoint. autobrr publishes no OpenAPI spec (docs/ holds only man pages), so this table is maintained by hand against autobrr's `internal/http/<resource>.go` handler `Routes` methods (currently pinned to develop HEAD). Each entry carries name/method/path/path-params/query-params/body-kind/doc.
- Excluded on purpose: `/api/auth` (session/OIDC, not usable over an API token), `/api/events` (SSE stream, not JSON), the inbound `/api/webhook` list-trigger routes (same job as `/api/lists/refresh`), and `/api/logs/files/{logFile}` (raw text download).
- Response caveats: healthz endpoints return `text/plain` ("OK") and `/api/feeds/{id}/latest` returns a raw string body — `_req` falls back to `r.text` for non-JSON 2xx bodies and returns `{}` for empty bodies, and `dispatch` is typed `JSONVal | str` accordingly. Keep that union widened; a too-narrow return type breaks structured-content validation at runtime.
- To refresh coverage after an autobrr update, diff `internal/http/*.go` `Routes` methods and update `_TOOL_REGISTRY` + `_GROUPS` by hand. Do not hand-edit generated per-endpoint functions; `register_tools()` regenerates them from the registry.
- Endpoint function naming (internal, not an MCP tool name): `autobrr_<verb>_<resource>` derived from path + method (e.g. `autobrr_list_filters`, `autobrr_create_filter`, `autobrr_delete_releases`, `autobrr_retry_release_action`).

## Portmanteau registration — **do not go back to one tool per endpoint**
- `_GROUPS` buckets every `_TOOL_REGISTRY` name into one of 13 resource groups (`autobrr_filters`, `autobrr_release`, `autobrr_config`, ...). `register_tools()` registers exactly one MCP tool per group via `_register_group`, which wraps the group's endpoint functions in a single `dispatch(operation, arguments)` closure. The endpoint functions themselves are plain callables looked up by name, not separately-registered tools.
- `operation` is typed `Literal[<the group's endpoint names>]`, so FastMCP/pydantic validates it against the real endpoint list before `dispatch` ever runs — an invalid operation never reaches the group tool's body.
- Adding a new endpoint: add its entry to `_TOOL_REGISTRY`, then add its name to exactly one group in `_GROUPS`. `tests/test_tools.py::test_all_registry_names_grouped` fails if you forget.
- New resource area big enough to need its own group (rare): add a new `_GROUPS` key. Keep the total group count at or under ~15 — that ceiling is the entire point of this pattern. The ~104-endpoint surface is exactly why a 104-tool server is unacceptable here.
- If you're tempted to add a per-endpoint `@mcp.tool` or an extra `mcp.add_tool` call outside `_register_group`, don't — every endpoint must be reachable only via its group's `operation` enum.

## Annotations convention
- A group tool is `readOnlyHint=True` (`READONLY`) only when *every* operation in it is a GET (`autobrr_system` is the one all-GET group today). Mixed groups carry no hints.
- Per-operation write/destructive notes survive in the group tool's description: each operation line still ends with its original one-line doc, and write/destructive endpoints keep a `WRITE:`/`DESTRUCTIVE:` note in that doc string. Some GETs are side-effecting (duplicate filter, IRC network restart) — they carry a `WRITE:` note too.

## Auth and base path
- Auth: `X-API-Token` header (create a key in autobrr Settings > API Keys). Also accepted by autobrr as `?apikey=` or a session cookie, but the header is what the MCP client sends.
- `build_client` points at the origin with no path suffix; every registered tool carries its full `/api/...` path. `_req` raises `ToolError` with the API status and message on `>=400`.
- If the autobrr instance is served under a base URL subpath, the user includes it in `AUTOBRR_URL`.

## Release workflow
Always use the `make bump-*` targets to bump the version (`uv version --bump patch|minor|major`), which updates `pyproject.toml` and `uv.lock` together. Do NOT edit the version by hand.

- Bump: `make bump-patch` (or `bump-minor` / `bump-major`)
- Commit message is **just the version**, e.g. `0.1.2` — nothing else.
- Tag it `v<version>` (e.g. `v0.1.2`).
- Push main and the tag:
  ```
  git push origin main
  git push origin v<version>
  ```
- Deploy to the Proxmox host (root SSH key): pull the repo then reinstall the uv tool:
  ```
  ssh root@192.168.50.3 -- 'cd /root/autobrr-mcp && git fetch origin && git reset --hard origin/main'
  ssh root@192.168.50.3 -- 'cd /root/autobrr-mcp && uv tool install --force .'
  ```
  The host runs it via `uv tool install` → `/root/.local/bin/autobrr-mcp` (not from the repo). Register it in `/root/.config/opencode/opencode.jsonc` with `AUTOBRR_URL`/`AUTOBRR_API_KEY`.

## Initial state
Version starts at `0.0.0` in the initial commit. No tag on the scaffold commit; releases begin at the first `make bump-*`.
