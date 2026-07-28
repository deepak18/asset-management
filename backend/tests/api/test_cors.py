"""CORS middleware contract tests.

The browser blocks the dev frontend (:3000) from calling this API (:8000) unless
the server answers with the right ``Access-Control-*`` headers. We drive the real
app in-process (httpx ``ASGITransport``, no socket) and assert the middleware is
wired and config-driven — both the actual-request header and the preflight (an
``OPTIONS`` with ``Access-Control-Request-Method``) that the browser sends first.

``create_app`` reads ``get_settings()`` at construction time, so each test patches
``app.main.get_settings`` to return a fixed allow-list. That keeps the assertions
deterministic regardless of any real ``.env`` on the developer's machine.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.core.config import Settings
from app.main import create_app

ALLOWED_ORIGIN = "http://localhost:3000"
DISALLOWED_ORIGIN = "http://evil.example.com"


def _client_with_origins(
    monkeypatch: pytest.MonkeyPatch, origins: list[str]
) -> AsyncClient:
    """Build an httpx client over the real app pinned to a fixed CORS allow-list."""

    settings = Settings(_env_file=None, cors_allow_origins=origins)  # type: ignore[call-arg]
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_allowed_origin_gets_cors_header(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _client_with_origins(monkeypatch, [ALLOWED_ORIGIN]) as client:
        resp = await client.get("/health", headers={"Origin": ALLOWED_ORIGIN})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


@pytest.mark.asyncio
async def test_disallowed_origin_gets_no_cors_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _client_with_origins(monkeypatch, [ALLOWED_ORIGIN]) as client:
        resp = await client.get("/health", headers={"Origin": DISALLOWED_ORIGIN})
    # The request still succeeds server-side; the browser is what enforces the
    # absence of the allow header by refusing to expose the response to JS.
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_preflight_allows_configured_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _client_with_origins(monkeypatch, [ALLOWED_ORIGIN]) as client:
        resp = await client.options(
            "/api/v1/portfolios/1",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "GET" in resp.headers["access-control-allow-methods"]

