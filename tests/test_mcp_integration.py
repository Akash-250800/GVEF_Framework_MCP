"""These run on the user's machine where MCP SDK v2 is installed."""
import asyncio
import pytest


@pytest.mark.asyncio
async def test_real_mcp_server_roundtrip():
    pytest.importorskip("mcp")
    from mcp.client import Client
    from server import make_server
    async with Client(make_server(),mode="legacy") as client:
        names={t.name for t in (await client.list_tools()).tools}
        assert {"check_stock","reserve_stock"}.issubset(names)
        result=await client.call_tool("check_stock",{"sku":"PEN"})
        assert not result.is_error


@pytest.mark.asyncio
async def test_real_mcp_bfcl_roundtrip():
    pytest.importorskip("mcp")
    from mcp.client import Client
    from benchmarks import make_bfcl_server
    task={"bfcl_tools":[{"name":"double","description":"Double a value", "input_schema":{"type":"object","properties":{"x":{"type":"integer"}},"required":["x"]}}]}
    async with Client(make_bfcl_server(task),mode="legacy") as client:
        names=[t.name for t in (await client.list_tools()).tools]
        assert "double" in names
        result=await client.call_tool("double",{"x":3})
        assert not result.is_error
