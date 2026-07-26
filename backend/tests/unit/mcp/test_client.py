"""Parsing MCP tool results into text (no transport)."""

from __future__ import annotations

import pytest
from mcp.types import CallToolResult, TextContent

from app.mcp.client import extract_text
from app.mcp.errors import McpToolError


def _text(value: str) -> TextContent:
    return TextContent(type="text", text=value)


def test_extract_single_text_block() -> None:
    result = CallToolResult(content=[_text('{"price": 1}')])
    assert extract_text(result, "GLOBAL_QUOTE") == '{"price": 1}'


def test_extract_joins_multiple_text_blocks() -> None:
    result = CallToolResult(content=[_text("line1"), _text("line2")])
    assert extract_text(result, "TOOL") == "line1\nline2"


def test_error_result_raises_tool_error() -> None:
    result = CallToolResult(content=[_text("boom")], isError=True)
    with pytest.raises(McpToolError, match="boom"):
        extract_text(result, "TOOL")


def test_no_text_content_raises_tool_error() -> None:
    result = CallToolResult(content=[])
    with pytest.raises(McpToolError, match="no text content"):
        extract_text(result, "TOOL")
