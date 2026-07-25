"""Config-only provider selection (AGENTS.md §4)."""

from __future__ import annotations

import pytest

from app.ai.client import LLMClient
from app.ai.factory import build_llm_client
from app.ai.providers.ollama import OllamaClient
from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    # Ignore any ambient .env so selection is driven purely by the values under test.
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_default_provider_builds_ollama_client() -> None:
    client = build_llm_client(_settings(ai_provider="ollama"))
    assert isinstance(client, OllamaClient)
    # Structural conformance to the interface callers depend on.
    assert isinstance(client, LLMClient)


def test_provider_selection_is_case_and_whitespace_insensitive() -> None:
    client = build_llm_client(_settings(ai_provider="  Ollama  "))
    assert isinstance(client, OllamaClient)


def test_ollama_client_is_wired_from_settings() -> None:
    settings = _settings(
        ai_provider="ollama",
        ai_model="llama3.1",
        ai_embedding_model="mxbai-embed-large",
        ai_request_timeout_seconds=42.0,
        ollama_base_url="http://ollama.local:11434/",
    )
    client = build_llm_client(settings)
    assert isinstance(client, OllamaClient)
    # Trailing slash is normalised so path joins stay clean.
    assert client._base_url == "http://ollama.local:11434"
    assert client._model == "llama3.1"
    assert client._embedding_model == "mxbai-embed-large"
    assert client._timeout == 42.0


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini", "GEMINI"])
def test_future_providers_raise_not_implemented(provider: str) -> None:
    with pytest.raises(NotImplementedError):
        build_llm_client(_settings(ai_provider=provider))


def test_unknown_provider_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown AI_PROVIDER"):
        build_llm_client(_settings(ai_provider="cohere"))
