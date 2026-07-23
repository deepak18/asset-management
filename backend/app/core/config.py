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
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings loaded from the environment / ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Default to an async SQLite file so the app is runnable with zero infra;
    # production overrides this with a postgresql+asyncpg URL (see .env.example).
    database_url: str = "sqlite+aiosqlite:///./asset_management.db"

    # Currency-aware from day one (PLAN.md decision #8): USD enabled now, INR next.
    # NoDecode: stop pydantic-settings from JSON-parsing the env var so our
    # `_split_csv` validator can accept a plain "USD,INR" string.
    base_currency: str = "USD"
    supported_currencies: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["USD"]
    )

    # Free-tier market data is served from a read-through cache (PLAN.md §1.3).
    marketdata_cache_ttl_seconds: int = 3600

    # Single local user (PLAN.md decision #1): optional local gate, no multi-tenant.
    api_access_key: str | None = None

    # AI provider is config-only switchable (§4); business logic never changes.
    ai_provider: str = "ollama"

    @field_validator("supported_currencies", mode="before")
    @classmethod
    def _split_csv(cls, value: str | list[str]) -> list[str]:
        """Allow ``SUPPORTED_CURRENCIES=USD,INR`` (CSV) as well as a JSON list."""

        if isinstance(value, str):
            return [code.strip().upper() for code in value.split(",") if code.strip()]
        return [code.upper() for code in value]

    @field_validator("base_currency")
    @classmethod
    def _normalize_base(cls, value: str) -> str:
        return value.upper()


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached settings instance."""

    return Settings()
