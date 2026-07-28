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
├── docker-compose.yml         # 🟡 Local orchestration: db (pgvector) active; api/mcp-gateway/frontend/ollama pending
├── backend/                   # 🟡 Python FastAPI service — deterministic core + REST API built (see below)
├── frontend/                  # 🟡 Next.js app — dashboard scaffolded, mocks-first (see below)
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
├── openapi.json               # ✅ Generated OpenAPI contract (the frontend-track seam; regen from app.main:app)
├── README.md                  # ✅ Backend dev/runbook (uv sync, pytest commands)
├── alembic.ini                # ✅ Alembic config (URL sourced from Settings at runtime, not hardcoded)
├── Dockerfile                 # ⬜ API container image
├── migrations/                # ✅ Alembic versioned migrations (async env)
│   ├── env.py                 # ✅ Async migration runner — reuses app engine, target_metadata=Base.metadata
│   ├── script.py.mako         # ✅ Revision script template
│   └── versions/
│       ├── 0001_initial_portfolio_schema.py  # ✅ Creates portfolios/holdings/transactions/cash_balances
│       ├── 0002_enable_pgvector.py            # ✅ Enables pgvector extension (Postgres-only, no-op on SQLite)
│       └── 0003_market_data_cache.py          # ✅ Creates market_data_cache (read-through cache table)
├── tests/                     # 🟡 pytest suites — mirrors app/ layout one-to-one (see AGENTS.md §11)
│   ├── conftest.py            # ✅ Shared fixtures (FX rate tables + in-memory async SQLite session)
│   ├── test_migrations.py     # ✅ Alembic upgrade/downgrade + model-vs-migration column drift guard
│   ├── factories/             # ⬜ Fixture builders (portfolios, transactions, filings, documents)
│   ├── unit/                  # 🟡 Pure/isolated tests — all provider boundaries mocked
│   │   ├── core/             # ✅ currency (FX normalization) + config edge cases
│   │   │   ├── test_currency.py   # ✅ base/identity, dated rates, missing-rate, cross-currency
│   │   │   └── test_config.py     # ✅ defaults, CSV currencies, env override + cache_clear
│   │   ├── portfolio/         # ✅ calculators (XIRR, P&L, allocation) — exhaustive edge cases
│   │   │   ├── test_allocation.py # ✅ weights by ticker/sector/industry, empty/zero-total
│   │   │   ├── test_cost_basis.py # ✅ FIFO realized/unrealized, splits, dividends, fees, mixed-ccy
│   │   │   ├── test_service.py    # ✅ service orchestration (grouping, roll-ups, XIRR, market values/allocation, unpriced) — faked providers
│   │   │   └── test_xirr.py       # ✅ pinned XIRR (10%/20%/neg, Excel ref), mixed-ccy, error paths
│   │   ├── providers/         # ✅ SQLAlchemy portfolio provider round-trip (in-memory SQLite)
│   │   │   └── test_portfolio_provider.py # ✅ ORM→schema mapping, exact Decimals, feeds calculators
│   │   ├── marketdata/        # ✅ read-through cache + AlphaVantage provider (mocked MCP) + throttle
│   │   │   ├── test_schemas.py    # ✅ provenance required, frozen, statement container, optional fields
│   │   │   ├── test_cache.py      # ✅ hit / miss-refresh / TTL-expiry / stale-fallback / per-symbol keys
│   │   │   ├── test_throttle.py   # ✅ min-interval spacing with injected clock/sleep
│   │   │   └── test_alphavantage.py # ✅ tool-JSON → typed mapping, cache-first, throttle, rate-limit/stale, bad symbol
│   │   ├── mcp/               # ✅ MCP registry + result parsing (no transport opened)
│   │   │   ├── test_registry.py   # ✅ apikey query construction, disabled-when-no-url
│   │   │   └── test_client.py     # ✅ extract_text: single/multi block, isError, no-content
│   │   ├── research/          # ⬜ competitor matrix assembly, news linking (mocked providers)
│   │   ├── documents/         # ⬜ PDF/TXT/MD parsing + citation anchors (mocked embeddings)
│   │   ├── citations/         # ⬜ polymorphic citation schema validation + enforcement
│   │   ├── ai/                # ✅ LLMClient factory selection + Ollama adapter (HTTP boundary mocked)
│   │   │   ├── test_factory.py       # ✅ config-only provider selection, future/unknown seams
│   │   │   └── test_ollama_client.py # ✅ request shaping, typed parsing, structured JSON, timeout/error translation
│   │   ├── api/                   # ✅ Route contract tests via httpx ASGITransport (in-process app)
│   │   │   ├── conftest.py        # ✅ Seeded in-memory SQLite + get_session/market-data overrides + AsyncClient fixtures
│   │   │   └── test_portfolio_routes.py # ✅ health, summary/txns/holdings/analytics (cost-basis + market values), 200 + 404
│   └── integration/           # 🟡 @pytest.mark.integration — real Postgres/pgvector + MCP/Ollama wiring (opt-in)
│       ├── test_postgres_pgvector.py # ✅ connect + CREATE EXTENSION vector + vector column round-trip
│       ├── test_ollama_live.py        # ✅ live Ollama completion + embedding smoke (skips if daemon down)
│       └── test_alphavantage_live.py  # ✅ live hosted AlphaVantage MCP list_tools + quote (skips if unconfigured)
├── scripts/                   # 🟡 Dev utilities — NOT shipped (hatch builds only app/), excluded from the lint gate
│   ├── portfolio_demo_1_2.py  # ✅ End-to-end deterministic-core demo: DB → provider → calculators (in-memory, no infra)
│   └── ollama_healthcheck.py  # ✅ Ollama connectivity/latency diagnostic (reachability, installed models, timed completion)
└── app/
    ├── main.py                # ✅ FastAPI app factory + lifespan (DB engine on state) + /health; mounts v1 router
    ├── core/                  # 🟡 Cross-cutting infra (NOT business logic)
    │   ├── config.py          # ✅ Pydantic Settings — env-driven (base/supported currency, DB URL, AI provider)
    │   ├── database.py        # ✅ Async engine (pooled + pre_ping for Postgres) + session factory + declarative Base
    │   ├── logging.py         # ⬜ Structured logging config
    │   ├── security.py        # ⬜ Single-user local gate (optional API_ACCESS_KEY) — no multi-tenant
    │   ├── currency.py        # ✅ FX normalization seam (Money/FxRate/FxRateTable) — USD now, INR-ready
    │   └── exceptions.py      # ⬜ App-wide error types + handlers
    ├── api/                   # 🟡 HTTP layer only (thin controllers, no business logic)
    │   ├── deps.py            # ✅ Shared FastAPI dependencies (session → provider(s) → service DI chain; market data optional)
    │   └── v1/
    │       ├── router.py      # ✅ Aggregates all v1 routes
    │       └── routes/        # 🟡 portfolio.py ✅; research.py, documents.py, marketdata.py, workspace.py ⬜
    │           └── portfolio.py   # ✅ GET portfolio/transactions/holdings/analytics (thin controllers + 404)
    ├── providers/             # 🟡 Strongly-typed abstraction interfaces (§2) — the ONLY I/O boundary
    │   ├── base.py            # ✅ PortfolioProvider Protocol (structural typing)
    │   ├── portfolio_provider.py  # ✅ SqlAlchemyPortfolioProvider — ORM rows → typed domain objects
    │   ├── marketdata_provider.py  # ✅ MarketDataProvider Protocol — quotes/profiles/statements (cache-first)
    │   ├── competitor_matrix_engine.py
    │   ├── sec_provider.py
    │   ├── news_streaming_engine.py
    │   └── document_provider.py
    ├── portfolio/             # 🟡 Ledger, allocation weights, investor returns (XIRR), valuations (pure Python)
    │   ├── models.py          # ✅ SQLAlchemy 2.0 mapped: Portfolio, Holding, Transaction, Cash (exact Decimal, currency-aware)
    │   ├── schemas.py         # ✅ Pydantic typed inputs/outputs (Transaction, CashFlow, PortfolioSummary, HoldingInfo, PortfolioAnalytics) — no dict/Any
    │   ├── service.py         # ✅ Orchestration: provider I/O × pure calculators → PortfolioAnalytics (+ market values via MarketDataProvider; no math, no I/O)
    │   └── calculators.py     # ✅ Pure math: FIFO cost-basis P&L, realized/unrealized, allocation, XIRR (unit-tested)
    ├── research/              # ⬜ Competitor matrix (manual peer seed), news streaming, evaluation workspaces
    ├── documents/             # ⬜ Ingestion pipeline, PDF/TXT/MD parsing, pgvector embeddings
    ├── marketdata/            # 🟡 Pricing + fundamentals behind MarketDataProvider; AlphaVantage-over-MCP wired
    │   ├── schemas.py         # ✅ Typed Quote/CompanyProfile/FinancialStatement(s) + MarketDataProvenance (citation seam §7)
    │   ├── models.py          # ✅ SQLAlchemy: market_data_cache (one row per provider/data_type/symbol)
    │   ├── cache.py           # ✅ ReadThroughCache — TTL freshness + stale fallback, generic over the payload schema
    │   ├── throttle.py        # ✅ AsyncRateLimiter — spaces upstream calls for the free tier (injectable clock/sleep)
    │   ├── alphavantage.py    # ✅ AlphaVantageMarketDataProvider — MCP tool JSON → typed schemas, cache-first, throttled
    │   └── errors.py          # ✅ MarketDataError / MarketDataUnavailableError
    ├── workspace_panel/       # ⬜ Context-aware AI panel (POST /workspace/ask → SSE token stream)
    ├── citations/             # ⬜ Polymorphic citation models + persistence (see PLAN.md citation schema)
    │   ├── models.py          # SQLAlchemy: base Citation + Document / Filing / StructuredData variants
    │   └── schemas.py         # Pydantic typed citation payloads
    ├── ai/                    # 🟡 AI provider abstraction (§4) built; orchestration (§6) pending
    │   ├── schemas.py         # ✅ Typed carriers: Role/ChatMessage/ChatRequest/ChatResponse/Embedding* (frozen, no dict/Any)
    │   ├── errors.py          # ✅ Typed error hierarchy: LLMError → Timeout/Unavailable/Response
    │   ├── client.py          # ✅ LLMClient Protocol — complete / complete_structured / embed (Ollama default, cloud via config only)
    │   ├── factory.py         # ✅ build_llm_client(settings) — config-only provider selection (ollama now; cloud = seams)
    │   ├── providers/         # 🟡 ollama.py ✅ (httpx adapter, mocked in unit tests); openai/anthropic/gemini ⬜
    │   │   └── ollama.py      # ✅ OllamaClient — /api/chat + /api/embeddings, config-driven timeout, typed error translation
    │   ├── agents/            # ⬜ PydanticAI single-shot tools
    │   ├── graphs/            # ⬜ LangGraph state machines (equity research report, etc.)
    │   └── citations.py       # ⬜ Zero-trust citation enforcement (§7)
    └── mcp/                    # 🟡 MCP client interfaces used by providers (§5)
        ├── client.py          # ✅ McpClient Protocol + StreamableHttpMcpClient (hosted HTTP) + extract_text
        ├── registry.py        # ✅ McpServerConfig + build_alphavantage_config (apikey → query param)
        └── errors.py          # ✅ McpError / McpUnavailableError / McpToolError
```

---

## Frontend (`frontend/`) — Next.js (App Router), TypeScript, Tailwind, shadcn/ui

Talks to the backend **only** through the versioned REST API (§9). No DB access.
Built and tested against MSW mocks derived from `backend/openapi.json` (the seam);
swaps mocks for live calls by config. Full runbook: `frontend/README.md`.

```
frontend/
├── package.json               # ✅ Deps + scripts (dev/build/test/lint/typecheck/typegen); esbuild override; msw workerDir
├── package-lock.json          # ✅ npm-locked dependency graph
├── next.config.ts             # ✅ Next config (reactStrictMode; no API proxy — REST-only seam)
├── tsconfig.json              # ✅ Strict TS (noUncheckedIndexedAccess), @/* path alias
├── next-env.d.ts              # ✅ Next-generated ambient types (do not edit)
├── tailwind.config.ts         # ✅ Theme wired to CSS custom-property design tokens
├── postcss.config.mjs         # ✅ Tailwind + Autoprefixer pipeline
├── eslint.config.mjs          # ✅ ESLint 9 flat config (spreads eslint-config-next flat arrays)
├── .prettierrc.json           # ✅ Formatter config (LF, double quotes)
├── vitest.config.ts           # ✅ Vitest + React Testing Library (jsdom), @/ alias
├── vitest.setup.ts            # ✅ jest-dom matchers + MSW server lifecycle + ResizeObserver stub
├── .env.local.example         # ✅ NEXT_PUBLIC_API_BASE_URL + NEXT_PUBLIC_API_MOCKING
├── .gitignore                 # ✅ node_modules/.next/env/coverage/generated worker
├── README.md                  # ✅ Runbook (install, dev, test, typegen, mock-vs-live, money model)
├── Dockerfile                 # ⬜ Frontend container image
├── public/
│   └── mockServiceWorker.js   # 🟡 MSW browser worker (generated by `npx msw init`, git-ignored)
└── src/
    ├── app/                   # ✅ App Router
    │   ├── layout.tsx         # ✅ Root layout: globals, terminal chrome (Nav), Providers
    │   ├── page.tsx           # ✅ dashboard: summary + allocation + ledger + watchlist
    │   ├── providers.tsx      # ✅ Client bootstrap; mounts MSW mock (next/dynamic ssr:false) in mock mode
    │   └── globals.css        # ✅ Tailwind layers + light/dark design tokens
    ├── components/
    │   ├── ui/                # ✅ shadcn-style primitives: card, badge, skeleton, table, button, input
    │   ├── shared/            # ✅ states.tsx — loading / error / empty blocks (honest "—", no fake 0)
    │   ├── portfolio/         # ✅ views
    │   │   ├── portfolio-summary.tsx   # ✅ Headline stats; unpriced/null → "Not priced"/"—"
    │   │   ├── allocation-chart.tsx    # ✅ Recharts donut + accessible legend (sector/industry)
    │   │   ├── allocation-section.tsx  # ✅ Data wrapper feeding the donuts from analytics
    │   │   ├── transaction-ledger.tsx  # ✅ Ledger grid; type-aware cells (dash irrelevant fields)
    │   │   └── watchlist.tsx           # ✅ Add/remove tickers (localStorage-backed)
    │   ├── app-shell/         # ✅ nav.tsx — top bar + light/dark toggle
    │   ├── research/          # ⬜ Ticker workstation, competitor matrix, thesis canvas
    │   └── workspace-panel/   # ⬜ Context-aware side panel (streaming tokens)
    ├── hooks/                 # ✅ Data + UI state hooks
    │   ├── use-api-resource.ts        # ✅ Generic async state (loading/error/success), stale-response guard
    │   ├── use-portfolio.ts           # ✅ Endpoint hooks bound to the typed client
    │   └── use-watchlist.ts           # ✅ localStorage watchlist (normalized, de-duplicated)
    ├── lib/                   # ✅ Client-side infra
    │   ├── env.ts             # ✅ Validated public env (API base URL, mock flag)
    │   ├── api-client.ts      # ✅ Typed REST client (the ONLY backend channel) + ApiError
    │   ├── decimal.ts         # ✅ Float-free Decimal-string parse/round/scale helpers
    │   ├── format.ts          # ✅ money/percent/quantity formatting; DASH for null/unpriced
    │   └── utils.ts           # ✅ cn() class-merge helper
    ├── mocks/                 # ✅ MSW mock layer (contract-shaped)
    │   ├── fixtures.ts        # ✅ Typed fixtures (priced / unpriced / empty portfolios)
    │   ├── handlers.ts        # ✅ Request handlers implementing the OpenAPI routes
    │   ├── server.ts          # ✅ Node server for Vitest (msw/node)
    │   ├── browser.ts         # ✅ Browser worker (msw/browser) — client-only
    │   └── mock-bootstrap.tsx # ✅ Client-only worker starter (loaded via ssr:false)
    ├── types/                 # ✅ Contract types
    │   ├── api.ts             # ✅ GENERATED by openapi-typescript from backend/openapi.json (tool-owned)
    │   └── domain.ts          # ✅ Friendly aliases over the generated schemas
    └── __tests__/             # ✅ Vitest + RTL specs
        ├── lib/               # ✅ decimal, format, api-client (MSW-backed)
        └── components/        # ✅ portfolio-summary, allocation-chart, transaction-ledger, watchlist
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
