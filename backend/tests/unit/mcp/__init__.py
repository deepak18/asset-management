"""Unit tests for the MCP client layer (registry + result parsing).

The transport/session is never opened here — we test config building and the pure
``extract_text`` helper against constructed SDK result objects.
"""

