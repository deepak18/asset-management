"""Application configuration via environment variables.

Why `pydantic-settings`? It gives us the same strong-typing guarantees as the rest
of the app (§8): env vars are parsed, validated, and coerced into typed fields
instead of being read as raw ``os.environ`` strings scattered across the codebase.
One ``Settings`` object is the single, typed source of configuration truth.

`get_settings()` is cached with ``lru_cache`` so the ``.env`` file + environment are
read exactly once per process; tests call ``get_settings.cache_clear()`` to force a
re-read after monkeypatching env vars.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The .env used by `docker compose` lives at the repo root. Resolve it from this
# file's location so the backend loads the same file whether commands run from the
# repo root or from backend/. A local ./.env (relative to CWD) is layered on top,
# and missing files are silently ignored by pydantic-settings.
_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Typed application settings loaded from the environment / ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=(_ROOT_ENV, ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Default to an async SQLite file so the app is runnable with zero infra;
    # production overrides this with a postgresql+asyncpg URL (see .env.example).
    database_url: str = "sqlite+aiosqlite:///./asset_management.db"

    # Connection-pool tuning for server DBs (Postgres). Ignored for SQLite.
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Currency-aware from day one (PLAN.md decision #8): USD enabled now, INR next.
    # NoDecode: stop pydantic-settings from JSON-parsing the env var so our
    # `_split_csv` validator can accept a plain "USD,INR" string.
    base_currency: str = "USD"
    supported_currencies: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["USD"]
    )

    # Free-tier market data is served from a read-through cache (PLAN.md §1.3).
    marketdata_cache_ttl_seconds: int = 3600

    # AlphaVantage market data via the official hosted MCP server. The API key
    # and MCP URL are config-only; an empty URL disables the live provider
    # (unit tests never need it). The min-request interval throttles upstream calls to
    # respect the free tier (~5 req/min → ~12s spacing); the cache absorbs the rest.
    alphavantage_api_key: str | None = None
    alphavantage_mcp_url: str | None = "https://mcp.alphavantage.co/mcp"
    marketdata_min_request_interval_seconds: float = 12.0

    # Single local user (PLAN.md decision #1): optional local gate, no multi-tenant.
    api_access_key: str | None = None

    # Browser same-origin policy blocks the dev frontend (:3000) from calling this
    # API (:8000) unless the server opts in via CORS. Env-configurable so prod can
    # widen/narrow the allow-list without code changes. NoDecode lets the validator
    # accept a plain "http://a,http://b" CSV as well as a JSON list.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # AI provider is config-only switchable; business logic never changes.
    ai_provider: str = "ollama"

    # Model + inference-hub knobs consumed by app/ai/. The wrapper is pure I/O
    # behind the LLMClient interface, so changing provider/model/timeout is a
    # config-only edit — no business or agent code changes. Defaults mirror
    # .env.example so a fresh clone talks to a local Ollama out of the box.
    ai_model: str = "qwen2.5"
    ai_embedding_model: str = "nomic-embed-text"
    # `float` (not Decimal) is correct here: these are httpx timeouts, not money.
    # `ai_request_timeout_seconds` is the READ/generation budget — it must be
    # generous because CPU-only (no-GPU) inference plus a one-off model load can
    # take minutes; too small a value fails on slowness rather than real errors.
    # `ai_connect_timeout_seconds` stays short so an unreachable/firewalled host
    # fails fast instead of hanging for the full generation budget.
    ai_request_timeout_seconds: float = 300.0
    ai_connect_timeout_seconds: float = 5.0
    ollama_base_url: str = "http://localhost:11434"

    @field_validator("supported_currencies", mode="before")
    @classmethod
    def _split_csv(cls, value: str | list[str]) -> list[str]:
        """Allow ``SUPPORTED_CURRENCIES=USD,INR`` (CSV) as well as a JSON list."""

        if isinstance(value, str):
            return [code.strip().upper() for code in value.split(",") if code.strip()]
        return [code.upper() for code in value]

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: str | list[str]) -> list[str]:
        """Allow ``CORS_ALLOW_ORIGINS=http://a,http://b`` (CSV) or a JSON list.

        Origins are compared verbatim by the browser, so unlike currency codes
        they are neither upper-cased nor otherwise normalized — only trimmed.
        """

        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return [origin.strip() for origin in value]

    @field_validator("base_currency")
    @classmethod
    def _normalize_base(cls, value: str) -> str:
        return value.upper()


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached settings instance."""

    return Settings()
