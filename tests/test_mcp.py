import pytest
from mcp import Client
from src.mcp_server import mcp

@pytest.mark.anyio
async def test_healthcheck():
    async with Client(mcp) as client:
        result = await client.call_tool("healthcheck", {})
        assert result.is_error is False
