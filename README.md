# asset-management

Local AI-powered **Investment Research Platform** — an analytical terminal (think Bloomberg / Koyfin / NotebookLM), **not** a chatbot. Runs locally on Ollama, with the frontend, backend API, and MCP servers deployable independently.

> 📐 **Architecture rules:** see [`AGENTS.md`](./AGENTS.md)
> 🗺️ **Build roadmap:** see [`PLAN.md`](./PLAN.md)
> 🧭 **Directory source of truth:** see [`STRUCTURE.md`](./STRUCTURE.md) — read before writing code.

---

## Tech Stack
- **Frontend:** Next.js · React · TypeScript · Tailwind · shadcn/ui
- **Backend:** Python · FastAPI · SQLAlchemy 2.0 (async) · Alembic
- **DB / Vectors:** PostgreSQL + `pgvector`
- **AI:** PydanticAI (single-shot) + LangGraph (state machines); Ollama default, cloud via config
- **Integration:** Model Context Protocol (MCP) clients

## Layout (high level)
```
backend/   FastAPI service — domain modules behind provider interfaces
frontend/  Next.js app — talks to backend via REST only
mcp/       MCP server configs/wrappers (AlphaVantage, SEC EDGAR, filesystem, browser)
infra/     Deployment manifests (compose overrides, k8s/ECS)
```

## Getting Started (planned)
1. `cp .env.example .env` and fill in values (see **Secrets** below).
2. `docker compose up -d` — starts Postgres (pgvector), API, MCP gateway, Ollama, frontend.
3. Backend (managed with **uv**): `cd backend && uv sync`, run Alembic migrations, then `uv run uvicorn app.main:app --reload`.
4. Frontend: `cd frontend && npm install && npm run dev` (defaults to http://localhost:3000).

> Detailed commands land here as each module is scaffolded per `PLAN.md`.

## Testing
Tests are written **side-by-side with code** — a change isn't done until its tests pass (see `AGENTS.md` §11).
- **Backend:** `pytest` + `pytest-asyncio` + `pytest-cov`; `backend/tests/` mirrors `backend/app/`.
  - Fast unit run: `cd backend && uv run pytest`
  - Integration (real DB/MCP, opt-in): `uv run pytest -m integration`
  - Coverage: `uv run pytest --cov=app`
- **Frontend:** Vitest + React Testing Library — `cd frontend && npm run test`.
- Financial math has exhaustive edge-case coverage; AI tests assert structure/citations, never exact LLM wording.

## Secrets & Configuration
- Every variable is documented in [`.env.example`](./.env.example); the real `.env` is git-ignored.
- Config is loaded centrally via `backend/app/core/config.py` (Pydantic `BaseSettings`).
- Switching AI provider is **config-only** (`AI_PROVIDER` + keys) — no code changes.
- Never commit API keys, `.env`, or uploaded documents.

## Contributing / Agent Protocol
- Update `STRUCTURE.md` whenever files or folders change.
- Ship tests in the same change as the code (`pytest` backend, Vitest frontend) — untested logic is incomplete.
- Keep business logic deterministic; AI never computes financial figures (see `AGENTS.md` §1, §7).
- Cross-module access goes through `providers/` interfaces only.

