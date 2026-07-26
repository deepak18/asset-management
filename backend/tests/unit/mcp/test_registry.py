"""Config-only MCP server registry construction."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.core.config import Settings
from app.mcp.registry import build_alphavantage_config


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_no_url_disables_provider() -> None:
    assert build_alphavantage_config(_settings(alphavantage_mcp_url="")) is None


def test_api_key_is_appended_as_query_param() -> None:
    config = build_alphavantage_config(
        _settings(
            alphavantage_mcp_url="https://mcp.alphavantage.co/mcp",
            alphavantage_api_key="SECRET123",
        )
    )
    assert config is not None
    assert config.name == "alphavantage"
    assert parse_qs(urlparse(config.url).query)["apikey"] == ["SECRET123"]


def test_existing_apikey_is_not_duplicated() -> None:
    config = build_alphavantage_config(
        _settings(
            alphavantage_mcp_url="https://mcp.alphavantage.co/mcp?apikey=ALREADY",
            alphavantage_api_key="SECRET123",
        )
    )
    assert config is not None
    assert config.url.count("apikey=") == 1
    assert "ALREADY" in config.url


def test_existing_query_uses_ampersand_separator() -> None:
    config = build_alphavantage_config(
        _settings(
            alphavantage_mcp_url="https://host/mcp?foo=bar",
            alphavantage_api_key="KEY",
        )
    )
    assert config is not None
    assert "?foo=bar&apikey=KEY" in config.url


def test_no_key_leaves_url_untouched() -> None:
    config = build_alphavantage_config(
        _settings(alphavantage_mcp_url="https://host/mcp", alphavantage_api_key="")
    )
    assert config is not None
    assert config.url == "https://host/mcp"
