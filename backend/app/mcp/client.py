"""A thin, typed MCP client wrapper over the official ``mcp`` SDK.

``McpClient`` is the interface the rest of the app depends on: "call this tool with
these string arguments, give me back the JSON text of the result." Concrete
transports (streamable HTTP now; stdio later) implement it without leaking session
or transport details upward (§2/§3).

Why return *text*? MCP tool results are dynamic JSON. Rather than pass bare dicts
around (forbidden by §8), the client hands back the raw JSON string and each
provider validates it into its own typed schema at the edge — the same
"typed at the boundary" discipline used for the Ollama wire models.

The streamable-HTTP client opens a fresh short-lived session per call. That is
simple and robust for a request/response data source; call volume is already held
down by the read-through cache and the upstream throttle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, TextContent

from app.mcp.errors import McpToolError, McpUnavailableError
from app.mcp.registry import McpServerConfig


class McpClient(Protocol):
    """Call MCP tools and get back their JSON text result."""

    async def call_tool(self, tool: str, arguments: Mapping[str, str]) -> str:
        """Invoke ``tool`` with string ``arguments``; return its JSON text result."""
        ...

    async def list_tools(self) -> tuple[str, ...]:
        """Return the names of tools the server advertises (for discovery)."""
        ...


def extract_text(result: CallToolResult, tool: str) -> str:
    """Pull the concatenated text content out of a tool result, or raise.

    Separated from the transport so it can be unit-tested directly against
    constructed ``CallToolResult`` objects (no network).
    """

    if result.isError:
        raise McpToolError(f"MCP tool '{tool}' returned an error: {_join_text(result)}")
    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    if not texts:
        raise McpToolError(f"MCP tool '{tool}' returned no text content")
    return "\n".join(texts)


def _join_text(result: CallToolResult) -> str:
    return " ".join(block.text for block in result.content if isinstance(block, TextContent))


class StreamableHttpMcpClient:
    """``McpClient`` backed by the MCP streamable-HTTP transport (hosted servers)."""

    def __init__(self, config: McpServerConfig) -> None:
        self._config = config

    async def call_tool(self, tool: str, arguments: Mapping[str, str]) -> str:
        try:
            async with streamablehttp_client(
                self._config.url, headers=dict(self._config.headers)
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, dict(arguments))
        except McpToolError:
            raise
        except Exception as exc:  # noqa: BLE001 — wrap any SDK/transport failure
            raise McpUnavailableError(
                f"MCP call '{tool}' to {self._config.name} failed: {exc}"
            ) from exc
        return extract_text(result, tool)

    async def list_tools(self) -> tuple[str, ...]:
        try:
            async with streamablehttp_client(
                self._config.url, headers=dict(self._config.headers)
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listing = await session.list_tools()
        except Exception as exc:  # noqa: BLE001 — wrap any SDK/transport failure
            raise McpUnavailableError(
                f"MCP list_tools to {self._config.name} failed: {exc}"
            ) from exc
        return tuple(tool.name for tool in listing.tools)







