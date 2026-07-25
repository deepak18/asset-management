"""Typed error hierarchy for the AI subsystem.

The adapters translate raw transport failures (httpx timeouts, connection
refusals, non-2xx responses, malformed bodies) into these domain errors so
callers never have to catch ``httpx.*`` — the concrete transport stays hidden
behind the ``LLMClient`` interface (§3/§4). Callers can branch on intent:

* ``LLMTimeoutError``     — the model did not respond within ``AI_REQUEST_TIMEOUT_SECONDS``.
* ``LLMUnavailableError`` — the inference hub is unreachable (e.g. Ollama not running).
* ``LLMResponseError``    — a response arrived but was an HTTP error or unparseable.

All inherit ``LLMError``, so a caller that only cares "did the AI call fail?"
catches the base and degrades gracefully.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for every failure surfaced by an ``LLMClient`` implementation."""


class LLMTimeoutError(LLMError):
    """The provider did not respond within the configured timeout window."""


class LLMUnavailableError(LLMError):
    """The provider could not be reached (connection refused / DNS / network)."""


class LLMResponseError(LLMError):
    """The provider replied, but with an HTTP error or an unparseable body."""
