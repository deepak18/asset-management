"""The ``LLMClient`` interface — the ONLY seam business code depends on.

Like ``providers/base.py``, this is a ``typing.Protocol`` (structural typing):
an adapter "is" an ``LLMClient`` simply by exposing the right async methods, with
no inheritance required. Agents, RAG pipelines, and the workspace panel depend on
this abstraction, never on ``OllamaClient`` (or a future ``OpenAIClient``) — which
is what makes provider swapping a config-only change.

Three capabilities cover Phase 1–2 needs:

* ``complete`` — free-text chat/completion (summaries, explanations).
* ``complete_structured`` — same call but constrained to a Pydantic schema, so the
  model must return JSON we can validate into a typed object. This is the backbone
  of citation-anchored, strongly-typed AI output: we assert on the *schema*,
  never on prose.
* ``embed`` — turn text into a vector for ``pgvector`` retrieval.

Note the boundary carries **no business logic**: it moves typed data in and
typed data out. All financial math stays in the deterministic core.
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from app.ai.schemas import ChatRequest, ChatResponse, EmbeddingRequest, EmbeddingResponse

# Bound to BaseModel so ``complete_structured`` can both drive the provider's
# JSON-schema constraint and validate the reply back into that exact type.
StructuredT = TypeVar("StructuredT", bound=BaseModel)


@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic access to a chat model and an embedding model."""

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Run a chat/completion and return the model's free-text answer."""
        ...

    async def complete_structured(
        self, request: ChatRequest, schema: type[StructuredT]
    ) -> StructuredT:
        """Run a completion constrained to ``schema`` and parse the JSON reply.

        Raises ``LLMResponseError`` if the model's output cannot be validated
        against ``schema`` — a broken contract is surfaced, never silently coerced.
        """
        ...

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Return an embedding vector for ``request.text``."""
        ...
