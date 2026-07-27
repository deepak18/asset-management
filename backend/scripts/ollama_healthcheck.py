"""Ollama connectivity + latency diagnostic (dev utility, not shipped).

Separates three failure modes that matter for a remote / GPU-less daemon:

1. **Reachability** — a fast ``GET /api/version`` (short connect timeout). If this
   fails, it's networking (wrong IP, ``OLLAMA_HOST`` not ``0.0.0.0``, firewall).
2. **Installed models** — ``GET /api/tags`` lists what's actually pulled, so you
   know whether ``AI_MODEL`` exists on that box before you try to use it.
3. **Real latency** — a timed one-token completion through the *actual* app path
   (``OllamaClient``), so you see the true cold-start + generation cost on that
   hardware and can size ``AI_REQUEST_TIMEOUT_SECONDS`` accordingly.

Config comes from the root ``.env`` (``OLLAMA_BASE_URL``, ``AI_MODEL``, timeouts);
override the URL/model ad hoc with ``--url`` / ``--model``.

Run:
    uv run python scripts/ollama_healthcheck.py
    uv run python scripts/ollama_healthcheck.py --url http://192.168.1.42:11434 --model llama3.2:3b
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx

from app.ai.errors import LLMError
from app.ai.schemas import ChatMessage, ChatRequest, Role
from app.core.config import get_settings

# Import the concrete adapter directly: this is a diagnostic that intentionally
# pins the Ollama path (the app itself still selects providers via the factory).
from app.ai.providers.ollama import OllamaClient  # noqa: E402  (kept beside its siblings)


async def _run(base_url: str, model: str, embedding_model: str, timeout: float) -> int:
    print(f"→ Ollama base URL : {base_url}")
    print(f"→ chat model      : {model}")
    print(f"→ read timeout    : {timeout}s\n")

    # 1) Reachability — fast probe, short connect timeout.
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(10.0, connect=5.0)) as http:
            version = (await http.get("/api/version")).json()
            print(f"[ok] reachable — Ollama version {version.get('version', '?')}")

            # 2) Installed models.
            tags = (await http.get("/api/tags")).json()
            names = sorted(m["name"] for m in tags.get("models", []))
            print(f"[ok] installed models ({len(names)}): {', '.join(names) or '(none)'}")
            if model not in names and model.split(':')[0] not in {n.split(':')[0] for n in names}:
                print(f"[warn] '{model}' is not installed — run:  ollama pull {model}")
    except httpx.HTTPError as exc:
        print(f"[FAIL] cannot reach Ollama at {base_url}: {exc}")
        print("       check the IP, that OLLAMA_HOST=0.0.0.0 on that machine, and the firewall.")
        return 1

    # 3) Real latency through the app path.
    client = OllamaClient(
        base_url=base_url,
        model=model,
        embedding_model=embedding_model,
        timeout_seconds=timeout,
    )
    try:
        print("\n[..] timing a tiny completion (first call includes model load)...")
        started = time.perf_counter()
        response = await client.complete(
            ChatRequest(messages=(ChatMessage(role=Role.USER, content="Reply with just: ok"),))
        )
        elapsed = time.perf_counter() - started
        preview = response.content.strip().replace("\n", " ")[:60]
        print(f"[ok] completion in {elapsed:.1f}s — model={response.model} — reply='{preview}'")
        if elapsed > timeout * 0.5:
            print(f"[warn] that used >50% of the {timeout}s budget; consider raising it.")
    except LLMError as exc:
        print(f"[FAIL] completion failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        await client.aclose()

    print("\nAll checks passed.")
    return 0


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Diagnose the Ollama connection.")
    parser.add_argument("--url", default=settings.ollama_base_url, help="Ollama base URL")
    parser.add_argument("--model", default=settings.ai_model, help="chat model to test")
    args = parser.parse_args()
    return asyncio.run(
        _run(
            base_url=args.url,
            model=args.model,
            embedding_model=settings.ai_embedding_model,
            timeout=settings.ai_request_timeout_seconds,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
