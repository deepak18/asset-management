"""Typed request/response carriers for the AI subsystem.

No ``dict`` or ``Any`` structural payloads cross the ``LLMClient`` boundary (§8):
callers hand in a frozen ``ChatRequest`` / ``EmbeddingRequest`` and get back a
frozen ``ChatResponse`` / ``EmbeddingResponse``. These are pure data — no I/O,
no logic — mirroring the discipline already used in ``portfolio/schemas.py``.

Why ``float`` here (unlike the ledger's ``Decimal``)? None of these fields are
money. ``temperature`` is a sampling knob and an embedding is a vector of model
activations; base-10 exactness is irrelevant, and vectors are consumed by
``pgvector`` as floats anyway.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    """Chat roles as understood by chat-completion APIs (Ollama, OpenAI, ...)."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    """A single turn in a chat conversation."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str


class ChatRequest(BaseModel):
    """A provider-agnostic chat/completion request.

    ``model`` is optional: when ``None`` the adapter falls back to its configured
    default (``AI_MODEL``), so callers only override when they truly need a
    specific model. ``temperature`` is likewise optional and left to the model's
    own default when unset.
    """

    model_config = ConfigDict(frozen=True)

    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    model: str | None = None
    temperature: float | None = None


class ChatResponse(BaseModel):
    """A parsed chat/completion result. ``model`` echoes what actually served it."""

    model_config = ConfigDict(frozen=True)

    model: str
    content: str


class EmbeddingRequest(BaseModel):
    """A request to embed a single piece of text (RAG groundwork, PLAN.md §2.1)."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    model: str | None = None


class EmbeddingResponse(BaseModel):
    """A parsed embedding vector plus the model that produced it."""

    model_config = ConfigDict(frozen=True)

    model: str
    embedding: tuple[float, ...] = Field(min_length=1)
