"""Offline tests: one per autobrr endpoint, plus error-path and portmanteau
grouping tests.

No network. The endpoint list is `_TOOL_REGISTRY` itself (autobrr publishes no
OpenAPI spec, so the registry is the source of truth), and each tool call is
checked against the exact HTTP request it should produce (method, path incl.
path-param substitution, query params) via httpx.MockTransport, using FastMCP's
in-memory Client (see https://gofastmcp.com/development/tests).
"""

import json

import httpx
import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError

import autobrr_mcp


class Recorder:
    """Captures the single request made during a test and replays a canned response."""

    def __init__(self):
        self.method = None
        self.url = None
        self.headers = None
        self.params = None
        self.json = None
        self.response = httpx.Response(200, json={"success": True})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.method = request.method
        self.url = request.url
        self.headers = request.headers
        self.params = request.url.params
        self.json = json.loads(request.content) if request.content else None
        return self.response


@pytest.fixture
def recorder():
    return Recorder()


@pytest_asyncio.fixture
async def server(recorder, monkeypatch):
    transport = httpx.MockTransport(recorder.handler)
    client = autobrr_mcp.build_client("https://autobrr.example.com", "test-token", transport=transport)
    monkeypatch.setattr(autobrr_mcp, "_client", client)
    yield autobrr_mcp.mcp
    await client.aclose()


def op_to_args(spec):
    """Build call args for a tool from its registry entry: path params get a
    sentinel value per their declared type."""
    args = {}
    for p in spec["pp"]:
        args[p["name"]] = "abc" if p["type"] == "str" else 1
    return args


def expected_path(spec):
    path = spec["path"]
    for p in spec["pp"]:
        path = path.replace("{" + p["wire"] + "}", "abc" if p["type"] == "str" else "1")
    return path


_OP_GROUP = {op: group for group, ops in autobrr_mcp._GROUPS.items() for op in ops}


async def call(server, tool, **kwargs):
    """Call `tool` (an endpoint operation name) through the portmanteau group
    tool that now hosts it, so every per-endpoint test keeps working via the
    group dispatcher."""
    async with Client(server) as c:
        return await c.call_tool(_OP_GROUP[tool], {"operation": tool, "arguments": kwargs})


# --- one test per endpoint ---------------------------------------------------

@pytest.mark.parametrize(
    "spec",
    autobrr_mcp._TOOL_REGISTRY,
    ids=[s["name"] for s in autobrr_mcp._TOOL_REGISTRY],
)
async def test_endpoint_mapping(server, recorder, spec):
    await call(server, spec["name"], **op_to_args(spec))
    assert recorder.method == spec["method"]
    assert recorder.url.path == expected_path(spec)


# --- coverage: registry == groups ---------------------------------------------

def test_all_registry_names_grouped():
    """Every registry endpoint must land in exactly one portmanteau group -
    this is the safety net for the group-tool consolidation."""
    registry_names = [s["name"] for s in autobrr_mcp._TOOL_REGISTRY]
    grouped_names = [n for names in autobrr_mcp._GROUPS.values() for n in names]
    assert sorted(grouped_names) == sorted(registry_names)
    assert len(grouped_names) == len(set(grouped_names))
    assert len(autobrr_mcp._GROUPS) <= 15


def test_all_registered_tools_have_unique_names():
    names = [s["name"] for s in autobrr_mcp._TOOL_REGISTRY]
    assert len(names) == len(set(names))


async def test_group_tools_are_the_only_registered_tools(server):
    async with Client(server) as c:
        tools = await c.list_tools()
    assert {t.name for t in tools} == set(autobrr_mcp._GROUPS)


async def test_readonly_hint_only_on_all_get_groups(server):
    async with Client(server) as c:
        tools = await c.list_tools()
    by_name = {t.name: t for t in tools}
    method_by_name = {s["name"]: s["method"] for s in autobrr_mcp._TOOL_REGISTRY}
    for group, names in autobrr_mcp._GROUPS.items():
        expected = {method_by_name[n] for n in names} == {"GET"}
        t = by_name[group]
        assert (t.annotations is not None and t.annotations.readOnlyHint) is expected


async def test_unknown_operation_rejected_by_schema(server):
    # The Literal[...] enum on `operation` means an invalid value never
    # reaches _register_group's dispatch body - pydantic rejects it first.
    with pytest.raises(ToolError, match="validation error"):
        async with Client(server) as c:
            await c.call_tool("autobrr_filters", {"operation": "not_a_real_operation"})


# --- query params --------------------------------------------------------------

async def test_query_params_use_wire_names(server, recorder):
    await call(server, "autobrr_list_releases", limit=50, offset=10, push_status="PUSH_APPROVED", q="linux")
    assert recorder.params["limit"] == "50"
    assert recorder.params["offset"] == "10"
    assert recorder.params["push_status"] == "PUSH_APPROVED"
    assert recorder.params["q"] == "linux"


async def test_list_params_serialize_repeatedly(server, recorder):
    await call(server, "autobrr_list_filters", indexer=["ptp", "btn"])
    assert recorder.params.get_list("indexer") == ["ptp", "btn"]


async def test_defaults_and_empties_are_omitted(server, recorder):
    await call(server, "autobrr_list_releases")
    assert "limit" not in recorder.params
    assert "offset" not in recorder.params
    assert "q" not in recorder.params

    await call(server, "autobrr_list_filters", indexer=[])
    assert "indexer" not in recorder.params


async def test_stats_days_param_sent_when_set(server, recorder):
    await call(server, "autobrr_get_release_stats_activity", days=7)
    assert recorder.params["days"] == "7"

    await call(server, "autobrr_get_release_stats_activity")
    assert "days" not in recorder.params


# --- request bodies ------------------------------------------------------------

async def test_body_sent_as_json(server, recorder):
    body = {"name": "test filter", "enabled": True, "indexers": ["btn"]}
    await call(server, "autobrr_create_filter", body=body)
    assert recorder.json == body


async def test_array_body_sent_as_json(server, recorder):
    body = [{"notification_id": 1, "enabled": True}]
    await call(server, "autobrr_update_filter_notifications", filter_id=1, body=body)
    assert recorder.json == body


async def test_path_params_substitute(server, recorder):
    await call(server, "autobrr_get_feed", feed_id=42)
    assert recorder.url.path == "/api/feeds/42"

    await call(server, "autobrr_get_irc_message_history", network_id=7, channel="autobrr")
    assert recorder.url.path == "/api/irc/network/7/channel/autobrr/history"

    await call(server, "autobrr_retry_release_action", release_id=5, action_status_id=9)
    assert recorder.url.path == "/api/release/5/actions/9/retry"


async def test_get_requests_have_no_body(server, recorder):
    await call(server, "autobrr_list_indexers")
    assert recorder.json is None


# --- response handling -----------------------------------------------------------

async def test_empty_response_becomes_empty_dict(server, recorder):
    recorder.response = httpx.Response(204, text="")
    result = await call(server, "autobrr_check_updates")
    assert result.data == {}


async def test_text_response_returned_as_string(server, recorder):
    recorder.response = httpx.Response(200, text="OK")
    result = await call(server, "autobrr_get_healthz_liveness")
    assert result.data == "OK"


# --- auth header -----------------------------------------------------------------

async def test_token_sent_as_x_api_token_header(server, recorder):
    await call(server, "autobrr_list_indexers")
    assert recorder.headers["x-api-token"] == "test-token"


async def test_no_token_means_no_auth_header(recorder, monkeypatch):
    transport = httpx.MockTransport(recorder.handler)
    client = autobrr_mcp.build_client("https://autobrr.example.com", None, transport=transport)
    monkeypatch.setattr(autobrr_mcp, "_client", client)
    await call(autobrr_mcp.mcp, "autobrr_list_indexers")
    assert "x-api-token" not in recorder.headers
    await client.aclose()


# --- error paths -----------------------------------------------------------------

async def test_404_error_message_reaches_caller(server, recorder):
    recorder.response = httpx.Response(404, json={"message": "could not find feed with id 999"})
    with pytest.raises(ToolError, match="could not find feed"):
        await call(server, "autobrr_get_feed", feed_id=999)


async def test_401_error_surfaces_status(server, recorder):
    recorder.response = httpx.Response(401, text="Unauthorized")
    with pytest.raises(ToolError, match="401"):
        await call(server, "autobrr_list_indexers")


async def test_400_error_surfaces_status(server, recorder):
    recorder.response = httpx.Response(400, json={"message": "limit parameter is invalid"})
    with pytest.raises(ToolError, match="400"):
        await call(server, "autobrr_list_releases", limit=0)


async def test_non_json_error_body_does_not_crash(server, recorder):
    recorder.response = httpx.Response(502, text="<html>Bad Gateway</html>")
    with pytest.raises(ToolError, match="502"):
        await call(server, "autobrr_list_indexers")


# --- main() ------------------------------------------------------------------

def test_main_requires_autobrr_url(monkeypatch):
    monkeypatch.delenv("AUTOBRR_URL", raising=False)
    with pytest.raises(SystemExit):
        autobrr_mcp.main()
