# asset-management backend

FastAPI service for the Local AI-powered Investment Research Platform.

**Implemented so far (PLAN.md §1.1–1.2):**
- Deterministic portfolio calculators — allocation, FIFO cost-basis P&L, realized/unrealized, XIRR (pure, side-effect-free).
- Currency-normalization seam (`core/currency.py`) — USD now, INR-ready.
- SQLAlchemy 2.0 async models + `PortfolioProvider` interface + orchestration service.
- Alembic migrations (portfolio schema + pgvector enablement).
- REST API: `/health`, `/api/v1/portfolios/{id}` (+ `/transactions`, `/holdings`, `/analytics`).

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

## Regenerate the OpenAPI contract

```bash
uv run python -c "import json; from pathlib import Path; from app.main import create_app; Path('openapi.json').write_text(json.dumps(create_app().openapi(), indent=2), encoding='utf-8')"
```


