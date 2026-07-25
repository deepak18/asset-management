"""Ollama adapter — the default local ``LLMClient`` (AGENTS.md §4, PLAN.md §1.1).

Talks to a running Ollama daemon over its HTTP API (``OLLAMA_BASE_URL``) using
``httpx``. This module is deliberately thin: shape a typed request into Ollama's
wire format, POST it, and parse the reply back into our typed schemas. There is
**no business logic** here (§1) — only transport.

Design choices worth calling out:

* **Typed at both edges.** Raw JSON never leaks into the codebase: outgoing bodies
  are built from private ``_Ollama*Payload`` models and incoming bodies are
  validated into private ``_Ollama*Response`` models the moment they arrive (§8).
* **Config-driven timeout + graceful failure.** The client is constructed with
  ``AI_REQUEST_TIMEOUT_SECONDS``; every transport failure (timeout, refused
  connection, HTTP error, unparseable body) is translated into the typed
  ``LLMError`` hierarchy so callers degrade gracefully and never see ``httpx.*``.
* **Injectable transport.** The constructor accepts an optional ``httpx.AsyncClient``
  so unit tests can drive a ``MockTransport`` — the HTTP boundary is mocked, no
  live Ollama is required.
* **Structured output** uses Ollama's ``format`` field: we pass the target model's
  JSON Schema so the daemon constrains generation, then validate the reply into
  that exact Pydantic type.

Ollama endpoints used: ``POST /api/chat`` and ``POST /api/embeddings``.
"""

from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.errors import LLMResponseError, LLMTimeoutError, LLMUnavailableError
from app.ai.schemas import (
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)

StructuredT = TypeVar("StructuredT", bound=BaseModel)


# --- Private wire models (Ollama's JSON shapes; never exposed to callers) -------


class _WireMessage(BaseModel):
    role: str
    content: str


class _OllamaOptions(BaseModel):
    """Ollama groups sampling knobs under ``options``."""

    model_config = ConfigDict(frozen=True)

    temperature: float | None = None


class _OllamaChatPayload(BaseModel):
    """Request body for ``POST /api/chat``."""

    model_config = ConfigDict(frozen=True)

    model: str
    messages: tuple[_WireMessage, ...]
    stream: bool = False
    # A JSON Schema (dict) constrains structured output; ``None`` for free text.
    # This is provider metadata, not a domain payload, so ``Any`` is acceptable here.
    format: dict[str, Any] | None = None
    options: _OllamaOptions | None = None


class _OllamaChatResponse(BaseModel):
    """Response body from ``POST /api/chat``."""

    model: str
    message: _WireMessage


class _OllamaEmbeddingPayload(BaseModel):
    """Request body for ``POST /api/embeddings``."""

    model_config = ConfigDict(frozen=True)

    model: str
    prompt: str


class _OllamaEmbeddingResponse(BaseModel):
    """Response body from ``POST /api/embeddings``."""

    embedding: tuple[float, ...] = Field(min_length=1)


# --- Adapter -------------------------------------------------------------------


class OllamaClient:
    """Default local ``LLMClient`` backed by an Ollama daemon.

    Structurally satisfies ``app.ai.client.LLMClient`` (no inheritance needed).
    Build one via ``app.ai.factory.build_llm_client`` so provider selection stays
    config-only.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        embedding_model: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._embedding_model = embedding_model
        self._timeout = timeout_seconds
        # When no client is injected we own the lifecycle and must close it.
        self._client = client
        self._owns_client = client is None

    # -- public API (LLMClient) -------------------------------------------------

    async def complete(self, request: ChatRequest) -> ChatResponse:
        payload = self._chat_payload(request, output_format=None)
        wire = await self._post_chat(payload)
        return ChatResponse(model=wire.model, content=wire.message.content)

    async def complete_structured(
        self, request: ChatRequest, schema: type[StructuredT]
    ) -> StructuredT:
        payload = self._chat_payload(request, output_format=schema.model_json_schema())
        wire = await self._post_chat(payload)
        try:
            return schema.model_validate_json(wire.message.content)
        except ValidationError as exc:
            raise LLMResponseError(
                f"Ollama response did not match {schema.__name__}: {exc}"
            ) from exc

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        model = request.model or self._embedding_model
        payload = _OllamaEmbeddingPayload(model=model, prompt=request.text)
        raw = await self._post("/api/embeddings", payload)
        wire = self._parse(_OllamaEmbeddingResponse, raw)
        return EmbeddingResponse(model=model, embedding=wire.embedding)

    async def aclose(self) -> None:
        """Dispose the underlying HTTP client if we created it."""

        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- internals --------------------------------------------------------------

    def _chat_payload(
        self, request: ChatRequest, *, output_format: dict[str, Any] | None
    ) -> _OllamaChatPayload:
        options = (
            _OllamaOptions(temperature=request.temperature)
            if request.temperature is not None
            else None
        )
        return _OllamaChatPayload(
            model=request.model or self._model,
            messages=tuple(
                _WireMessage(role=m.role.value, content=m.content) for m in request.messages
            ),
            format=output_format,
            options=options,
        )

    async def _post_chat(self, payload: _OllamaChatPayload) -> _OllamaChatResponse:
        raw = await self._post("/api/chat", payload)
        return self._parse(_OllamaChatResponse, raw)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        return self._client

    async def _post(self, path: str, payload: BaseModel) -> httpx.Response:
        client = self._get_client()
        try:
            response = await client.post(
                path, json=payload.model_dump(mode="json", exclude_none=True)
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama request to {path} timed out after {self._timeout}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"Ollama is unreachable at {self._base_url}: {exc}") from exc

        if response.status_code >= 400:
            raise LLMResponseError(
                f"Ollama returned HTTP {response.status_code} for {path}: {response.text}"
            )
        return response

    @staticmethod
    def _parse(model: type[StructuredT], response: httpx.Response) -> StructuredT:
        try:
            return model.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise LLMResponseError(f"Malformed Ollama response body: {exc}") from exc

