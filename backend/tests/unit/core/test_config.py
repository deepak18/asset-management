"""Tests for env-driven application settings (app.core.config)."""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings


def test_defaults_are_usd_and_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    # Assert true CODE defaults: isolate from any ambient env var or .env file so
    # this passes regardless of a developer's shell or a present repo-root .env.
    for var in ("DATABASE_URL", "BASE_CURRENCY", "SUPPORTED_CURRENCIES", "AI_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.base_currency == "USD"
    assert settings.supported_currencies == ["USD"]
    assert settings.ai_provider == "ollama"
    assert settings.database_url.startswith("sqlite+aiosqlite")


def test_ai_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate from any ambient AI_* env or .env so we assert true code defaults.
    for var in (
        "AI_MODEL",
        "AI_EMBEDDING_MODEL",
        "AI_REQUEST_TIMEOUT_SECONDS",
        "AI_CONNECT_TIMEOUT_SECONDS",
        "OLLAMA_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.ai_model == "qwen2.5"
    assert settings.ai_embedding_model == "nomic-embed-text"
    # Read/generation budget is generous (slow CPU inference); connect is snappy.
    assert settings.ai_request_timeout_seconds == 300.0
    assert settings.ai_connect_timeout_seconds == 5.0
    assert settings.ollama_base_url == "http://localhost:11434"


def test_ai_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MODEL", "llama3.1")
    monkeypatch.setenv("AI_REQUEST_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.local:11434")
    settings = Settings()
    assert settings.ai_model == "llama3.1"
    assert settings.ai_request_timeout_seconds == 30.0
    assert settings.ollama_base_url == "http://ollama.local:11434"


def test_marketdata_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "ALPHAVANTAGE_API_KEY",
        "ALPHAVANTAGE_MCP_URL",
        "MARKETDATA_MIN_REQUEST_INTERVAL_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.alphavantage_api_key is None
    assert settings.alphavantage_mcp_url == "https://mcp.alphavantage.co/mcp"
    assert settings.marketdata_min_request_interval_seconds == 12.0


def test_supported_currencies_accepts_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPPORTED_CURRENCIES", "usd, inr")
    settings = Settings()
    assert settings.supported_currencies == ["USD", "INR"]


def test_base_currency_is_uppercased(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASE_CURRENCY", "inr")
    assert Settings().base_currency == "INR"


def test_env_override_and_cache_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    get_settings.cache_clear()
    try:
        assert get_settings().ai_provider == "openai"
    finally:
        get_settings.cache_clear()
