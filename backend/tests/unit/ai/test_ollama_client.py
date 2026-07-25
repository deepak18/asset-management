"""OllamaClient behaviour with the HTTP boundary mocked (no live Ollama).

Strategy: inject an ``httpx.AsyncClient`` wired to an ``httpx.MockTransport``. The
handler captures each outgoing request (so we can assert request shaping) and
returns canned bodies (so we can assert typed parsing). Transport failures are
simulated by raising ``httpx.*`` from the handler and asserting the adapter
translates them into the typed ``LLMError`` hierarchy.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import BaseModel

from app.ai.errors import LLMResponseError, LLMTimeoutError, LLMUnavailableError
from app.ai.providers.ollama import OllamaClient
from app.ai.schemas import ChatMessage, ChatRequest, EmbeddingRequest, Role

Handler = Callable[[httpx.Request], httpx.Response]


def _make_client(handler: Handler) -> OllamaClient:
    """Build an OllamaClient whose transport is fully mocked."""

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://ollama.test:11434")
    return OllamaClient(
        base_url="http://ollama.test:11434",
        model="qwen2.5",
        embedding_model="nomic-embed-text",
        timeout_seconds=5.0,
        client=http_client,
    )


def _chat_ok(content: str = "Revenue rose 12% YoY.", model: str = "qwen2.5") -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"model": model, "message": {"role": "assistant", "content": content}}
        )

    return handler


# --- request shaping -----------------------------------------------------------


async def test_complete_shapes_chat_request_and_parses_response() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _chat_ok()(request)

    client = _make_client(handler)
    request = ChatRequest(
        messages=(
            ChatMessage(role=Role.SYSTEM, content="You are an equity analyst."),
            ChatMessage(role=Role.USER, content="Summarise the filing."),
        )
    )
    response = await client.complete(request)

    # Response parsed into the typed carrier.
    assert response.content == "Revenue rose 12% YoY."
    assert response.model == "qwen2.5"

    # Request shaping: correct endpoint + body.
    assert str(seen[0].url) == "http://ollama.test:11434/api/chat"
    body = json.loads(seen[0].content)
    assert body["model"] == "qwen2.5"  # falls back to configured default
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "You are an equity analyst."},
        {"role": "user", "content": "Summarise the filing."},
    ]
    # No structured format and no temperature → omitted (exclude_none).
    assert "format" not in body
    assert "options" not in body


async def test_complete_honours_model_and_temperature_overrides() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _chat_ok(model="llama3.1")(request)

    client = _make_client(handler)
    request = ChatRequest(
        messages=(ChatMessage(role=Role.USER, content="hi"),),
        model="llama3.1",
        temperature=0.2,
    )
    await client.complete(request)

    body = json.loads(seen[0].content)
    assert body["model"] == "llama3.1"
    assert body["options"] == {"temperature": 0.2}


# --- structured output ---------------------------------------------------------


class _Sentiment(BaseModel):
    label: str
    score: float


async def test_complete_structured_sends_schema_and_parses_typed_object() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        payload = json.dumps({"label": "bullish", "score": 0.8})
        return httpx.Response(
            200, json={"model": "qwen2.5", "message": {"role": "assistant", "content": payload}}
        )

    client = _make_client(handler)
    request = ChatRequest(messages=(ChatMessage(role=Role.USER, content="sentiment?"),))
    result = await client.complete_structured(request, _Sentiment)

    assert isinstance(result, _Sentiment)
    assert result.label == "bullish"
    assert result.score == 0.8

    # The JSON Schema of the target model is forwarded as Ollama's `format`.
    body = json.loads(seen[0].content)
    assert body["format"] == _Sentiment.model_json_schema()


async def test_complete_structured_raises_on_schema_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # `score` is not a number → validation must fail.
        payload = json.dumps({"label": "bullish", "score": "high"})
        return httpx.Response(
            200, json={"model": "qwen2.5", "message": {"role": "assistant", "content": payload}}
        )

    client = _make_client(handler)
    request = ChatRequest(messages=(ChatMessage(role=Role.USER, content="sentiment?"),))
    with pytest.raises(LLMResponseError, match="_Sentiment"):
        await client.complete_structured(request, _Sentiment)


# --- embeddings ----------------------------------------------------------------


async def test_embed_shapes_request_and_parses_vector() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    client = _make_client(handler)
    response = await client.embed(EmbeddingRequest(text="Apple Inc. 10-K risk factors"))

    assert response.embedding == (0.1, 0.2, 0.3)
    assert response.model == "nomic-embed-text"  # configured default

    assert str(seen[0].url) == "http://ollama.test:11434/api/embeddings"
    body = json.loads(seen[0].content)
    assert body == {"model": "nomic-embed-text", "prompt": "Apple Inc. 10-K risk factors"}


async def test_embed_honours_model_override() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"embedding": [1.0]})

    client = _make_client(handler)
    response = await client.embed(EmbeddingRequest(text="x", model="mxbai-embed-large"))

    assert response.model == "mxbai-embed-large"
    assert json.loads(seen[0].content)["model"] == "mxbai-embed-large"


# --- graceful error translation ------------------------------------------------


async def test_timeout_is_translated_to_llm_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client = _make_client(handler)
    request = ChatRequest(messages=(ChatMessage(role=Role.USER, content="hi"),))
    with pytest.raises(LLMTimeoutError):
        await client.complete(request)


async def test_connection_error_is_translated_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _make_client(handler)
    request = ChatRequest(messages=(ChatMessage(role=Role.USER, content="hi"),))
    with pytest.raises(LLMUnavailableError):
        await client.complete(request)


async def test_http_error_status_is_translated_to_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    client = _make_client(handler)
    request = ChatRequest(messages=(ChatMessage(role=Role.USER, content="hi"),))
    with pytest.raises(LLMResponseError, match="HTTP 500"):
        await client.complete(request)


async def test_malformed_body_is_translated_to_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Missing the required `message` field.
        return httpx.Response(200, json={"model": "qwen2.5"})

    client = _make_client(handler)
    request = ChatRequest(messages=(ChatMessage(role=Role.USER, content="hi"),))
    with pytest.raises(LLMResponseError, match="Malformed"):
        await client.complete(request)


async def test_aclose_is_noop_for_injected_client() -> None:
    # We injected the AsyncClient, so the adapter must NOT own/close it.
    client = _make_client(_chat_ok())
    await client.aclose()
    # Still usable after aclose because ownership stayed with the test.
    request = ChatRequest(messages=(ChatMessage(role=Role.USER, content="hi"),))
    response = await client.complete(request)
    assert response.content == "Revenue rose 12% YoY."

