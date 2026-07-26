"""MCP client layer — the backend's gateway to MCP servers.

Model Context Protocol (MCP) is the primary way we extend the system's data
visibility. This package holds a thin, typed wrapper over the official ``mcp``
Python SDK so the rest of the codebase calls tools through a small interface
(``McpClient``) instead of driving transports/sessions directly. Providers
(e.g. the AlphaVantage market-data adapter) depend on that interface, keeping the
transport (streamable HTTP now, stdio later) a swappable detail.
"""
