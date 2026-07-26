"""Opt-in live smoke test against the official hosted AlphaVantage MCP server.

Excluded from the fast default run. Needs a valid ``ALPHAVANTAGE_API_KEY`` (and the
default hosted ``ALPHAVANTAGE_MCP_URL``) in the environment / root ``.env``. Run::

    uv run pytest -m integration tests/integration/test_alphavantage_live.py

Asserts only on shape (the server advertises tools; a quote parses to a positive
price) — never on specific market values. Skips (never fails) when the provider is
not configured or the server/network is unavailable.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.core.config import get_settings
from app.mcp.client import StreamableHttpMcpClient
from app.mcp.errors import McpError
from app.mcp.registry import build_alphavantage_config

pytestmark = pytest.mark.integration


async def test_live_alphavantage_lists_tools_and_quotes() -> None:
    config = build_alphavantage_config(get_settings())
    if config is None or "apikey=" not in config.url:
        pytest.skip("AlphaVantage MCP not configured (URL/API key missing).")

    client = StreamableHttpMcpClient(config)
    try:
        tools = await client.list_tools()
        assert len(tools) > 0

        text = await client.call_tool("GLOBAL_QUOTE", {"symbol": "AAPL"})
        payload = json.loads(text)
    except McpError:
        pytest.skip("AlphaVantage MCP server unreachable; skipping live test.")

    quote = payload.get("Global Quote", {})
    assert Decimal(str(quote.get("05. price", "0"))) > 0

