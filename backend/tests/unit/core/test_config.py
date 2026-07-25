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
