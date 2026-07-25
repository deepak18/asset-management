"""AI provider abstraction (AGENTS.md §4).

The LLM is treated as an **isolated, asynchronous I/O subsystem** — it holds no
business logic (§1). Everything in this package is pure transport behind the
``LLMClient`` interface: shape a typed request, call a model, parse a typed
response. Provider selection (Ollama today; OpenAI/Anthropic/Gemini later) is a
config-only switch via ``build_llm_client`` — no caller ever imports a concrete
adapter.
"""

from __future__ import annotations

from app.ai.client import LLMClient
from app.ai.errors import (
    LLMError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.ai.factory import build_llm_client
from app.ai.schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    Role,
)

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "LLMClient",
    "LLMError",
    "LLMResponseError",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "Role",
    "build_llm_client",
]
