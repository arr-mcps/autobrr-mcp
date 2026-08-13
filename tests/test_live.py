"""Integration tests against a real autobrr instance.

Skipped unless AUTOBRR_URL and AUTOBRR_API_KEY are set. Run with:
    uv run pytest -m integration

GET endpoints run read-only against the live instance. Write tests
(POST/PUT/PATCH/DELETE) only run when AUTOBRR_WRITE_TESTS=1 and perform safe
create -> update -> delete cycles against scratch resources (a filter, an
api key), then clean up. Never point write tests at a production instance you
care about.
"""

import os
import uuid

import pytest
from fastmcp import Client

import autobrr_mcp

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("AUTOBRR_URL") and os.environ.get("AUTOBRR_API_KEY")),
        reason="requires AUTOBRR_URL and AUTOBRR_API_KEY",
    ),
]

WRITE_TESTS = os.environ.get("AUTOBRR_WRITE_TESTS") == "1"


@pytest.fixture(autouse=True)
def configure_client():
    autobrr_mcp._client = autobrr_mcp.build_client(os.environ["AUTOBRR_URL"], os.environ["AUTOBRR_API_KEY"])
    yield
    if autobrr_mcp._client is not None:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass


async def call(name, **kwargs):
    async with Client(autobrr_mcp.mcp) as c:
        return await c.call_tool(name, kwargs)


# --- read-only ------------------------------------------------------------

async def test_get_config():
    result = await call("autobrr_get_config")
    assert "version" in result.data
    assert "application" in result.data


async def test_list_indexers():
    result = await call("autobrr_list_indexers")
    assert isinstance(result.data, list)


async def test_list_filters():
    result = await call("autobrr_list_filters")
    assert isinstance(result.data, list)


async def test_list_releases():
    result = await call("autobrr_list_releases", limit=5)
    assert "data" in result.data
    assert "meta" in result.data


async def test_get_release_stats():
    result = await call("autobrr_get_release_stats")
    assert isinstance(result.data, dict)


async def test_healthz():
    result = await call("autobrr_get_healthz_liveness")
    assert result.data == "OK"


# --- write (only with AUTOBRR_WRITE_TESTS=1) --------------------------------

@pytest.mark.skipif(not WRITE_TESTS, reason="set AUTOBRR_WRITE_TESTS=1 to run write tests")
async def test_filter_lifecycle():
    name = f"mcp-test-{uuid.uuid4().hex[:8]}"
    created = await call("autobrr_create_filter", body={"name": name, "enabled": True, "indexers": ["mock"]})
    filter_id = created.data["id"]

    try:
        await call("autobrr_toggle_filter_enabled", filter_id=filter_id, body={"enabled": False})
        got = await call("autobrr_get_filter", filter_id=filter_id)
        assert got.data["enabled"] is False

        duplicate = await call("autobrr_duplicate_filter", filter_id=filter_id)
        dup_id = duplicate.data["id"]
        try:
            assert duplicate.data["name"].startswith(name)
        finally:
            await call("autobrr_delete_filter", filter_id=dup_id)
    finally:
        await call("autobrr_delete_filter", filter_id=filter_id)


@pytest.mark.skipif(not WRITE_TESTS, reason="set AUTOBRR_WRITE_TESTS=1 to run write tests")
async def test_api_key_lifecycle():
    keys_before = (await call("autobrr_list_api_keys")).data
    created = await call("autobrr_create_api_key", body={"name": f"mcp-test-{uuid.uuid4().hex[:8]}"})
    token = created.data["key"]

    try:
        keys_after = (await call("autobrr_list_api_keys")).data
        assert len(keys_after) == len(keys_before) + 1
    finally:
        await call("autobrr_delete_api_key", apikey=token)
