"""Provider selection — the single place that reads ``AI_PROVIDER``.

Business code calls ``build_llm_client(get_settings())`` and receives an
``LLMClient``; it never imports a concrete adapter. Switching from local Ollama to
a cloud model is therefore a ``.env`` edit (``AI_PROVIDER=openai`` + a key), not a
code change. The cloud branches are intentionally left as explicit ``NotImplemented``
seams so the contract is visible now and future adapters slot in without touching
any caller.
"""

from __future__ import annotations

from app.ai.client import LLMClient
from app.ai.providers.ollama import OllamaClient
from app.core.config import Settings

# Recognised-but-not-yet-built providers. Listing them makes the seam explicit and
# gives a precise "planned, not broken" error instead of a generic "unknown".
_FUTURE_PROVIDERS = frozenset({"openai", "anthropic", "gemini"})


def build_llm_client(settings: Settings) -> LLMClient:
    """Construct the configured ``LLMClient`` from typed settings.

    Raises ``NotImplementedError`` for a recognised cloud provider that has no
    adapter yet, and ``ValueError`` for an unrecognised ``AI_PROVIDER`` value.
    """

    provider = settings.ai_provider.strip().lower()

    if provider == "ollama":
        return OllamaClient(
            base_url=settings.ollama_base_url,
            model=settings.ai_model,
            embedding_model=settings.ai_embedding_model,
            timeout_seconds=settings.ai_request_timeout_seconds,
            connect_timeout_seconds=settings.ai_connect_timeout_seconds,
        )

    if provider in _FUTURE_PROVIDERS:
        raise NotImplementedError(
            f"AI_PROVIDER='{provider}' is a planned adapter but not implemented yet; "
            "use 'ollama' for now."
        )

    raise ValueError(
        f"Unknown AI_PROVIDER='{settings.ai_provider}'. "
        "Expected one of: ollama, openai, anthropic, gemini."
    )
