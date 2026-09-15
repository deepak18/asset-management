"""Declarative registry of MCP servers, built from typed settings.

A ``McpServerConfig`` is all a client needs to connect: a name, a URL, and any headers.
``build_alphavantage_config`` turns the app's settings into that config
for the official hosted AlphaVantage MCP server, appending the API key as the
``apikey`` query parameter the hosted server expects. Returning ``None`` lets
callers cleanly treat the live provider as "disabled" (unit tests never
construct it).

The config is considered disabled unless **both** the URL and the API key are
present. The URL has a usable default, so requiring the key too is what stops a
key-less install from firing a doomed request on every analytics call: the
hosted server rejects unauthenticated traffic, so those calls can only ever fail
slowly and then degrade to "unpriced". Refusing to build the client turns that
into an immediate, honest "market data is not configured".
"""

from __future__ import annotations

from urllib.parse import urlencode, urlparse

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings


class McpServerConfig(BaseModel):
    """Everything needed to open a session with one MCP server."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)


def _with_apikey(url: str, api_key: str) -> str:
    """Append ``apikey=<key>`` to ``url`` unless it already carries one."""

    if "apikey=" in (urlparse(url).query or ""):
        return url
    separator = "&" if urlparse(url).query else "?"
    return f"{url}{separator}{urlencode({'apikey': api_key})}"


def build_alphavantage_config(settings: Settings) -> McpServerConfig | None:
    """Build the AlphaVantage MCP server config, or ``None`` when not configured.

    Both a URL and an API key are required. A key-less config would produce a
    client that can only fail against the hosted server, so we disable it up
    front instead of paying a network round-trip per request to learn that.
    """

    url = (settings.alphavantage_mcp_url or "").strip()
    key = (settings.alphavantage_api_key or "").strip()
    if not url or not key:
        return None
    return McpServerConfig(name="alphavantage", url=_with_apikey(url, key))
