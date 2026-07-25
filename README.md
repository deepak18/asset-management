# asset-management

Local AI-powered **Investment Research Platform** — an analytical terminal (think Bloomberg / Koyfin / NotebookLM), **not** a chatbot. Runs locally on Ollama, with the frontend, backend API, and MCP servers deployable independently.

> 📐 **Architecture rules:** see [`AGENTS.md`](./AGENTS.md) \
> 🗺️ **Build roadmap:** see [`PLAN.md`](./PLAN.md) \
> 🧭 **Directory source of truth:** see [`STRUCTURE.md`](./STRUCTURE.md) — read before writing code.

---

## Tech Stack
- **Frontend:** Next.js · React · TypeScript · Tailwind · shadcn/ui *(not yet scaffolded)*
- **Backend:** Python 3.12+ · FastAPI · SQLAlchemy 2.0 (async) · Alembic
- **DB / Vectors:** PostgreSQL 16 + `pgvector` (via Docker)
- **AI:** PydanticAI (single-shot) + LangGraph (state machines); Ollama default, cloud via config *(in progress)*
- **Integration:** Model Context Protocol (MCP) clients *(planned)*
- **Tooling:** [`uv`](https://docs.astral.sh/uv/) (env + lock + run) · `ruff` · `mypy` · `pytest`

## Layout (high level)
```
backend/   FastAPI service — domain modules behind provider interfaces
frontend/  Next.js app — talks to backend via REST only          (planned)
mcp/       MCP server configs/wrappers                            (planned)
infra/     Deployment manifests (compose overrides, k8s/ECS)      (planned)
docker-compose.yml   Local orchestration (Postgres + pgvector today)
```

---

## Current Status (what actually works today)

| Capability | State |
|---|---|
| Deterministic portfolio calculators (allocation, FIFO cost-basis P&L, realized/unrealized, XIRR) | ✅ pure + unit-tested |
| Currency normalization seam (USD now, INR-ready) | ✅ |
| SQLAlchemy 2.0 async models + provider interface | ✅ |
| Alembic migrations (schema + pgvector enablement) | ✅ |
| REST API (`/health`, portfolio summary/transactions/holdings/analytics) | ✅ |
| PostgreSQL + pgvector via Docker Compose | ✅ |
| Ollama AI-client wrapper | 🚧 in progress |
| Market data (MCP), documents/RAG, research, workspace panel | ⬜ planned |
| Frontend | ⬜ planned |

The generated API contract lives at [`backend/openapi.json`](./backend/openapi.json) (the seam the frontend generates types from).

---

## Prerequisites
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — manages the Python version, virtualenv, lockfile, and command running.
- **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** — runs PostgreSQL + pgvector. (uv installs Python 3.12+ itself, so a system Python is not required.)

## Getting Started (fresh clone → running API)

**1. Configure environment.** Copy the template; the defaults work for local Docker as-is.
```powershell
cp .env.example .env
```
> One `.env` at the repo root serves **both** Docker Compose (variable substitution for `POSTGRES_*`) and the backend app (`DATABASE_URL`, `AI_*`, …). The backend resolves this root `.env` regardless of the directory you run commands from.

**2. Start the database** (PostgreSQL 16 + pgvector). First run pulls the image.
```powershell
docker compose up -d --wait      # blocks until the DB healthcheck passes
docker compose ps                # STATUS should read "healthy"
```

**3. Install backend dependencies** (creates `backend/.venv`, installs the async Postgres driver).
```powershell
cd backend
uv sync --extra dev --extra postgres
```

**4. Apply database migrations** (creates tables + enables the `vector` extension).
```powershell
uv run alembic upgrade head
```

**5. Run the API.**
```powershell
uv run uvicorn app.main:app --reload
```
Open **http://localhost:8000/docs** for interactive Swagger UI. `GET /health` works immediately; the portfolio routes serve data once a portfolio is seeded.

**Stop the stack:** `docker compose down` (keeps data) · `docker compose down -v` (wipes the data volume for a fresh DB).

---

## Testing
Tests are written **side-by-side with code** — a change isn't done until its tests pass (see `AGENTS.md` §11).
- **Backend:** `pytest` + `pytest-asyncio` + `pytest-cov`; `backend/tests/` mirrors `backend/app/`.
  - Fast unit run (offline, default): `cd backend && uv run pytest`
  - Integration (real Postgres/pgvector, opt-in): `uv run pytest -m integration` *(requires `docker compose up -d`)*
  - Coverage: `uv run pytest --cov=app`
  - Lint & types: `uv run ruff check .` · `uv run mypy`
- **Frontend:** Vitest + React Testing Library — `cd frontend && npm run test` *(once scaffolded)*.
- Financial math has exhaustive edge-case coverage; AI tests assert structure/citations, never exact LLM wording.

---

## Secrets & Configuration
- Every variable is documented in [`.env.example`](./.env.example); the real `.env` is git-ignored.
- Config is loaded centrally via `backend/app/core/config.py` (Pydantic `BaseSettings`), which reads the **root** `.env`.
- `DATABASE_URL` (e.g. `postgresql+asyncpg://postgres:postgres@localhost:5432/asset_management`) is the single knob that points the app at a database. The app connects to whatever is bound to that host/port — the Docker container publishes `localhost:5432`. To run alongside a local Postgres, change `POSTGRES_PORT` and the URL to avoid a port clash.
- Switching AI provider is **config-only** (`AI_PROVIDER` + keys) — no code changes.
- Never commit API keys, `.env`, or uploaded documents.

## Contributing / Agent Protocol
- Read `STRUCTURE.md` before writing; update it whenever files or folders change.
- Keep this `README.md` runnable — update setup/run/test steps in the same change that alters them (`AGENTS.md` protocol #8).
- Ship tests in the same change as the code (`pytest` backend, Vitest frontend) — untested logic is incomplete.
- Keep business logic deterministic; AI never computes financial figures (see `AGENTS.md` §1, §7).
- Cross-module access goes through `providers/` interfaces only.
- Commit in small, logically-scoped, one-line Conventional Commits (`AGENTS.md` protocol #7).

