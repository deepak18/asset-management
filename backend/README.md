# asset-management backend

FastAPI service for the Local AI-powered Investment Research Platform.

**Implemented so far (PLAN.md §1.1–1.2):**
- Deterministic portfolio calculators — allocation, FIFO cost-basis P&L, realized/unrealized, XIRR (pure, side-effect-free).
- Currency-normalization seam (`core/currency.py`) — USD now, INR-ready.
- SQLAlchemy 2.0 async models + `PortfolioProvider` interface + orchestration service.
- Alembic migrations (portfolio schema + pgvector enablement).
- REST API: `/health`, `/api/v1/portfolios/{id}` (+ `/transactions`, `/holdings`, `/analytics`).
- AI provider abstraction (`app/ai/`) — typed `LLMClient` interface + local Ollama adapter (`complete` / `complete_structured` / `embed`); switching provider is config-only (`AI_PROVIDER`), no code changes (§4).

## Develop (managed with `uv`)

```bash
cd backend
uv sync --extra dev                 # create venv + install deps (add --extra postgres for asyncpg)
uv run pytest                       # fast, offline unit suite (integration excluded)
uv run pytest -m integration        # opt-in integration suite (needs `docker compose up -d`)
uv run pytest --cov=app             # coverage
uv run ruff check .                 # lint
uv run mypy                         # strict type-check
```

## Run against Postgres

From the **repo root** first: `docker compose up -d --wait` (starts Postgres + pgvector), then:

```bash
cd backend
uv sync --extra dev --extra postgres
uv run alembic upgrade head         # create tables + enable pgvector
uv run uvicorn app.main:app --reload   # http://localhost:8000/docs
```

Config comes from the repo-root `.env` (see the main [README](../README.md)); `DATABASE_URL` selects the database. With no `.env`/env override, the app falls back to a local SQLite file for zero-infra runs.

## Point at a remote or slow (GPU-less) Ollama

The AI provider is config-only (`AGENTS.md` §4). To use an Ollama daemon on another
machine, set in the root `.env`:

```dotenv
OLLAMA_BASE_URL=http://192.168.1.42:11434    # that machine's LAN IP
AI_MODEL=llama3.2:3b                         # a small model for CPU-only boxes
AI_REQUEST_TIMEOUT_SECONDS=300               # generous READ budget for slow inference
AI_CONNECT_TIMEOUT_SECONDS=5                 # stays short: unreachable host fails fast
```

On the Ollama machine: set `OLLAMA_HOST=0.0.0.0` (so it listens on the network),
open TCP `11434` in the firewall, and `ollama pull <model>` the model you configured.

Diagnose the connection (reachability, installed models, real latency):

```bash
uv run python scripts/ollama_healthcheck.py
# or override ad hoc:
uv run python scripts/ollama_healthcheck.py --url http://192.168.1.42:11434 --model llama3.2:3b
```

The opt-in live smoke test uses the same config: `uv run pytest -m integration -k ollama`.

## Regenerate the OpenAPI contract

```bash
uv run python -c "import json; from pathlib import Path; from app.main import create_app; Path('openapi.json').write_text(json.dumps(create_app().openapi(), indent=2), encoding='utf-8')"
```
