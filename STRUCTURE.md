# STRUCTURE.md

> **Single Source of Truth** for the repository layout (mandated by `AGENTS.md`).
> Read this before writing code. Update it immediately after creating or altering any file/folder.
>
> Status legend: ✅ active · 🟡 scaffolded/placeholder · ⬜ planned (not yet created)

---

## Top-Level Layout

```
asset-management/
├── AGENTS.md                  # ✅ Agent operational protocol + core design principles
├── PLAN.md                    # ✅ Phased build roadmap + technology stack
├── STRUCTURE.md               # ✅ This file — directory source of truth
├── README.md                  # ✅ Human runbook (setup, run, deploy)
├── .gitignore                 # ✅ Ignore rules (secrets, envs, build artifacts)
├── .env.example               # ✅ Documented template of ALL environment variables
├── docker-compose.yml         # ⬜ Local orchestration: api, db (pgvector), mcp-gateway, frontend, ollama
├── backend/                   # 🟡 Python FastAPI service — deterministic portfolio core built (see below)
├── frontend/                  # ⬜ Next.js app (see below)
├── mcp/                       # ⬜ MCP server orchestration + configs (see below)
└── infra/                     # ⬜ Deployment manifests (compose overrides, k8s, ECS)
```

---

## Backend (`backend/`) — FastAPI, SQLAlchemy 2.0 async, PydanticAI + LangGraph

Module boundaries mirror the decoupled directories required by `AGENTS.md` §3.
Cross-module access happens **only** through the `providers/` interfaces (§2).

```
backend/
├── pyproject.toml             # ✅ Deps + tooling (ruff, mypy, pytest, pytest-asyncio, pytest-cov) — managed via uv
├── uv.lock                    # ✅ uv-locked dependency graph
├── README.md                  # ✅ Backend dev/runbook (uv sync, pytest commands)
├── alembic.ini                # ⬜ Alembic migration config
├── Dockerfile                 # ⬜ API container image
├── migrations/                # ⬜ Alembic versioned migrations
│   └── versions/
├── tests/                     # 🟡 pytest suites — mirrors app/ layout one-to-one (see AGENTS.md §11)
│   ├── conftest.py            # ✅ Shared fixtures (FX rate tables + in-memory async SQLite session)
│   ├── factories/             # ⬜ Fixture builders (portfolios, transactions, filings, documents)
│   ├── unit/                  # 🟡 Pure/isolated tests — all provider boundaries mocked
│   │   ├── core/             # ✅ currency (FX normalization) + config edge cases
│   │   │   ├── test_currency.py   # ✅ base/identity, dated rates, missing-rate, cross-currency
│   │   │   └── test_config.py     # ✅ defaults, CSV currencies, env override + cache_clear
│   │   ├── portfolio/         # ✅ calculators (XIRR, P&L, allocation) — exhaustive edge cases
│   │   │   ├── test_allocation.py # ✅ weights by ticker/sector/industry, empty/zero-total
│   │   │   ├── test_cost_basis.py # ✅ FIFO realized/unrealized, splits, dividends, fees, mixed-ccy
│   │   │   └── test_xirr.py       # ✅ pinned XIRR (10%/20%/neg, Excel ref), mixed-ccy, error paths
│   │   ├── providers/         # ✅ SQLAlchemy portfolio provider round-trip (in-memory SQLite)
│   │   │   └── test_portfolio_provider.py # ✅ ORM→schema mapping, exact Decimals, feeds calculators
│   │   ├── marketdata/        # ⬜ cache hit/miss, TTL/stale fallback, throttling, as_of stamping
│   │   ├── research/          # ⬜ competitor matrix assembly, news linking (mocked providers)
│   │   ├── documents/         # ⬜ PDF/TXT/MD parsing + citation anchors (mocked embeddings)
│   │   ├── citations/         # ⬜ polymorphic citation schema validation + enforcement
│   │   └── ai/                # ⬜ tool-routing, graph state transitions, citation presence (no prose asserts)
│   ├── api/                   # ⬜ Route contract tests via httpx ASGITransport (incl. /workspace/ask SSE)
│   └── integration/           # ⬜ @pytest.mark.integration — real Postgres/pgvector + MCP wiring (opt-in)
└── app/
    ├── main.py                # ⬜ FastAPI app factory, router registration, lifespan hooks
    ├── core/                  # 🟡 Cross-cutting infra (NOT business logic)
    │   ├── config.py          # ✅ Pydantic Settings — env-driven (base/supported currency, DB URL, AI provider)
    │   ├── database.py        # ✅ Async engine + session factory + declarative Base (pgvector setup later)
    │   ├── logging.py         # ⬜ Structured logging config
    │   ├── security.py        # ⬜ Single-user local gate (optional API_ACCESS_KEY) — no multi-tenant
    │   ├── currency.py        # ✅ FX normalization seam (Money/FxRate/FxRateTable) — USD now, INR-ready
    │   └── exceptions.py      # ⬜ App-wide error types + handlers
    ├── api/                   # ⬜ HTTP layer only (thin controllers, no business logic)
    │   ├── deps.py            # ⬜ Shared FastAPI dependencies (db session, auth, providers)
    │   └── v1/
    │       ├── router.py      # ⬜ Aggregates all v1 routes
    │       └── routes/        # ⬜ portfolio.py, research.py, documents.py, marketdata.py, workspace.py
    ├── providers/             # 🟡 Strongly-typed abstraction interfaces (§2) — the ONLY I/O boundary
    │   ├── base.py            # ✅ PortfolioProvider Protocol (structural typing)
    │   ├── portfolio_provider.py  # ✅ SqlAlchemyPortfolioProvider — ORM rows → typed domain objects
    │   ├── marketdata_provider.py
    │   ├── competitor_matrix_engine.py
    │   ├── sec_provider.py
    │   ├── news_streaming_engine.py
    │   └── document_provider.py
    ├── portfolio/             # 🟡 Ledger, allocation weights, investor returns (XIRR), valuations (pure Python)
    │   ├── models.py          # ✅ SQLAlchemy 2.0 mapped: Portfolio, Holding, Transaction, Cash (exact Decimal, currency-aware)
    │   ├── schemas.py         # ✅ Pydantic typed inputs/outputs (Transaction, CashFlow, PortfolioSummary, HoldingInfo) — no dict/Any
    │   ├── service.py         # ⬜ Orchestration for the portfolio domain
    │   └── calculators.py     # ✅ Pure math: FIFO cost-basis P&L, realized/unrealized, allocation, XIRR (unit-tested)
    ├── research/              # ⬜ Competitor matrix (manual peer seed), news streaming, evaluation workspaces
    ├── documents/             # ⬜ Ingestion pipeline, PDF/TXT/MD parsing, pgvector embeddings
    ├── marketdata/            # ⬜ Pricing + fundamental normalization + read-through Postgres cache (free-tier)
    ├── workspace_panel/       # ⬜ Context-aware AI panel (POST /workspace/ask → SSE token stream)
    ├── citations/             # ⬜ Polymorphic citation models + persistence (see PLAN.md citation schema)
    │   ├── models.py          # SQLAlchemy: base Citation + Document / Filing / StructuredData variants
    │   └── schemas.py         # Pydantic typed citation payloads
    ├── ai/                    # ⬜ AI provider abstraction (§4) + orchestration (§6)
    │   ├── client.py          # ⬜ LLM interface — Ollama default, cloud via config only
    │   ├── providers/         # ⬜ ollama.py, openai.py, anthropic.py, gemini.py adapters
    │   ├── agents/            # ⬜ PydanticAI single-shot tools
    │   ├── graphs/            # ⬜ LangGraph state machines (equity research report, etc.)
    │   └── citations.py       # ⬜ Zero-trust citation enforcement (§7)
    └── mcp/                   # ⬜ MCP client interfaces used by providers (§5)
        ├── client.py          # ⬜ Generic MCP client wrapper
        └── registry.py        # ⬜ Configured server registry (alphavantage, sec-edgar, fs, browser)
```

---

## Frontend (`frontend/`) — Next.js (App Router), TypeScript, Tailwind, shadcn/ui

Talks to the backend **only** through the versioned REST API (§9). No DB access.

```
frontend/
├── package.json               # ⬜
├── next.config.ts             # ⬜
├── tsconfig.json              # ⬜
├── tailwind.config.ts         # ⬜
├── vitest.config.ts           # ⬜ Vitest + React Testing Library config (jsdom env)
├── .env.local.example         # ⬜ Frontend-only public vars (NEXT_PUBLIC_API_BASE_URL)
├── Dockerfile                 # ⬜
├── public/                    # ⬜ Static assets
└── src/
    ├── app/                   # ⬜ App Router routes (dashboard, research, documents)
    ├── components/            # ⬜ UI components
    │   ├── ui/                # ⬜ shadcn/ui primitives
    │   ├── portfolio/         # ⬜ Summary, allocation charts, ledger grid, watchlist
    │   ├── research/          # ⬜ Ticker workstation, competitor matrix, thesis canvas
    │   └── workspace-panel/   # ⬜ Context-aware side panel (streaming tokens)
    ├── lib/                   # ⬜ API client, fetchers, formatting utils
    ├── hooks/                 # ⬜ React hooks (data fetching, streaming)
    ├── types/                 # ⬜ Shared TS types (ideally generated from OpenAPI)
    ├── styles/                # ⬜ Global styles
    └── __tests__/             # ⬜ Vitest + RTL specs co-located per component/hook/util
```

---

## MCP Orchestration (`mcp/`)

Configuration and, where needed, thin wrapper servers for Model Context Protocol integrations (§5).
The backend consumes these via `backend/app/mcp/` clients — it never calls providers directly.

```
mcp/
├── servers.json               # ⬜ Declarative registry of MCP servers + transport (stdio/http)
├── alphavantage/              # ⬜ Market data & fundamentals MCP config/wrapper
├── sec-edgar/                 # ⬜ Regulatory filings MCP config/wrapper
├── filesystem/                # ⬜ Local filesystem MCP config
├── browser/                   # ⬜ Browser automation MCP config
└── README.md                  # ⬜ How to run/register each server locally + in containers
```

---

## Environment & Secrets

- All configuration flows through environment variables loaded by `backend/app/core/config.py` (Pydantic `BaseSettings`).
- `.env.example` documents every variable; the real `.env` is git-ignored and never committed.
- Secrets (AlphaVantage key, cloud LLM keys, DB password) are injected at runtime, not baked into images.
- Switching AI provider (§4) is config-only: change `AI_PROVIDER` + related keys, no code edits.
- **Single local user:** no per-user data isolation; auth is an optional local `API_ACCESS_KEY` gate only.
- **Currency-aware from day one:** `BASE_CURRENCY`/`SUPPORTED_CURRENCIES` drive `core/currency.py`; USD enabled now, INR next with no schema changes.
- **Free-tier only:** market data is served through a read-through Postgres cache (`MARKETDATA_CACHE_TTL_SECONDS`) to survive rate limits.

---

## Testing Conventions

- **Tests ship with code, every turn** (`AGENTS.md` §11) — a change is incomplete without them.
- **Backend:** `pytest` + `pytest-asyncio` + `pytest-cov`. `backend/tests/` mirrors `backend/app/` one-to-one; provider boundaries are mocked in unit tests. Integration tests are marked `@pytest.mark.integration` and excluded from the fast default run.
  - Run: `uv run pytest` · integration: `uv run pytest -m integration` · coverage: `uv run pytest --cov=app`.
- **Frontend:** Vitest + React Testing Library, specs co-located under `src/__tests__/`. Run: `npm run test`.
- **What to assert for AI code:** structured output schemas, tool routing, LangGraph state transitions, and citation presence/shape — never exact LLM wording.
