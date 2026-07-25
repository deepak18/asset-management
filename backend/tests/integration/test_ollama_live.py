"""Opt-in live smoke test against a real local Ollama daemon.

Excluded from the fast default run (``uv run pytest``). Run explicitly with a
local Ollama up and the configured model pulled::

    uv run pytest -m integration tests/integration/test_ollama_live.py

It asserts only on *shape* — a non-empty completion and a non-empty embedding
vector — never on model prose (AGENTS.md §11). If the daemon is unreachable the
test is skipped rather than failed, so it never blocks a machine without Ollama.
"""

from __future__ import annotations

import pytest

from app.ai.errors import LLMUnavailableError
from app.ai.factory import build_llm_client
from app.ai.schemas import ChatMessage, ChatRequest, EmbeddingRequest, Role
from app.core.config import get_settings

pytestmark = pytest.mark.integration


async def test_live_ollama_completion_and_embedding() -> None:
    client = build_llm_client(get_settings())
    try:
        chat = await client.complete(
            ChatRequest(
                messages=(ChatMessage(role=Role.USER, content="Reply with the word: ok"),),
            )
        )
        assert chat.content.strip() != ""

        embedding = await client.embed(EmbeddingRequest(text="hello world"))
        assert len(embedding.embedding) > 0
    except LLMUnavailableError:
        pytest.skip("Ollama is not running locally; skipping live integration test.")
    finally:
        aclose = getattr(client, "aclose", None)
        if aclose is not None:
            await aclose()
