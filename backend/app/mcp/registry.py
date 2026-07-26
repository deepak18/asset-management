"""Declarative registry of MCP servers, built from typed settings.

A ``McpServerConfig`` is all a client needs to connect: a name, a URL, and any headers.
``build_alphavantage_config`` turns the app's settings into that config
for the official hosted AlphaVantage MCP server, appending the API key as the
``apikey`` query parameter the hosted server expects. Returning ``None`` when no
URL is configured lets callers cleanly treat the live provider as "disabled"
(unit tests never construct it).
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
    """Build the AlphaVantage MCP server config, or ``None`` if no URL is set."""

    url = (settings.alphavantage_mcp_url or "").strip()
    if not url:
        return None
    key = (settings.alphavantage_api_key or "").strip()
    full_url = _with_apikey(url, key) if key else url
    return McpServerConfig(name="alphavantage", url=full_url)
