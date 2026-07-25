"""Unit tests for the AI provider abstraction (app.ai).

The HTTP/Ollama boundary is mocked via ``httpx.MockTransport`` — no live daemon.
We assert on provider selection, request shaping, typed parsing, and error
translation; never on model prose.
"""
