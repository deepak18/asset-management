"""Typed failures at the MCP boundary.

Callers branch on intent without importing the SDK's transport exceptions:

* ``McpUnavailableError`` — could not reach / complete a session with the server.
* ``McpToolError``        — the server answered but the tool call itself errored
  (``isError``) or returned no usable content.
"""

from __future__ import annotations


class McpError(Exception):
    """Base class for MCP client failures."""


class McpUnavailableError(McpError):
    """The MCP server was unreachable or the session failed to complete."""


class McpToolError(McpError):
    """The MCP tool returned an error result or no usable content."""
