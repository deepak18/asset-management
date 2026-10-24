# STRUCTURE.md

> **Single Source of Truth** for the repository layout (mandated by `AGENTS.md`).
> Read this before writing code. Update it immediately after creating or altering any file/folder.
>
> Status legend: ✅ active · 🟡 scaffolded/placeholder · ⬜ planned (not yet created)

---

## Top-Level Layout

```
asset-management/
├── .github/
│   └── agents/                # ✅ Repository-scoped Copilot custom agents; discovery/delegation depends on IDE support
│       ├── project-orchestrator.agent.md # ✅ Plans delegated slices, validates and creates local commits by default, reporting hashes and remaining status
│       ├── backend-implementer.agent.md  # ✅ Backend-only implementation, typed API contract, pytest/ruff/mypy and exact commit handoff to the orchestrator
│       └── frontend-implementer.agent.md # ✅ Frontend-only OpenAPI/UI implementation, MSW/RTL/lint/typecheck and exact commit handoff to the orchestrator
├── AGENTS.md                  # ✅ Agent operational protocol, default local slice commits and core design principles
├── PLAN.md                    # ✅ Phased roadmap, delivered capabilities, resumable account/exposure contracts, sourced free-MCP research and gated EdgarTools stock/ETF integration plan
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
├── FRONTEND_HANDOFF.md         # ✅ Frontend-agent prompt for main-table history indicators, stable ledger IDs, confirmed deletion, mocks and regression tests
├── alembic.ini                # ✅ Alembic config (URL sourced from Settings at runtime, not hardcoded)
├── Dockerfile                 # ⬜ API container image
├── migrations/                # ✅ Alembic versioned migrations (async env)
│   ├── env.py                 # ✅ Async migration runner — reuses app engine, target_metadata=Base.metadata
│   ├── script.py.mako         # ✅ Revision script template
│   └── versions/
│       ├── 0001_initial_portfolio_schema.py  # ✅ Creates portfolios/holdings/transactions/cash_balances
│       ├── 0002_enable_pgvector.py            # ✅ Enables pgvector extension (Postgres-only, no-op on SQLite)
│       ├── 0003_market_data_cache.py          # ✅ Creates market_data_cache (read-through cache table)
│       ├── 0004_statement_imports.py          # ✅ Creates statement_imports (async import job metadata/progress; checksum indexed)
│       ├── 0005_import_recovery_and_provenance.py # ✅ Adds classification provenance (legacy labels → MANUAL), import ownership, retry safety, and unresolved records
│       ├── 0006_holding_return_history.py # ✅ Adds transaction origin for holding XIRR; legacy unowned history → UNKNOWN, owned import history → OBSERVED
│       ├── 0007_transaction_deletion.py # ✅ Adds nullable deletion tombstones; downgrade removes deleted events rather than resurrecting them
│       └── 0008_holding_history_confirmation.py # ✅ Adds nullable holding-scoped review-token and confirmation-time metadata without rewriting ledger facts
├── tests/                     # 🟡 pytest suites — mirrors app/ layout one-to-one (see AGENTS.md §11)
│   ├── conftest.py            # ✅ Shared fixtures (FX rate tables + in-memory async SQLite session)
│   ├── test_migrations.py     # ✅ Alembic upgrade/downgrade, drift/provenance/tombstone guards and nullable confirmation migration coverage
│   ├── factories/             # ⬜ Fixture builders (portfolios, transactions, filings, documents)
│   ├── unit/                  # 🟡 Pure/isolated tests — all provider boundaries mocked
    │   │   ├── core/             # ✅ currency (FX normalization) + config edge cases + engine factory
    │   │   │   ├── test_currency.py   # ✅ base/identity, dated rates, missing-rate, cross-currency
    │   │   │   ├── test_database.py   # ✅ sqlite engine builds; missing driver names the exact `uv sync` extra to install
    │   │   │   └── test_config.py     # ✅ defaults, CSV currencies + CORS origins, statement-import settings, env override + cache_clear
    │   │   ├── portfolio/         # ✅ calculators (XIRR, P&L, allocation) + write orchestration — exhaustive edge cases
    │   │   │   ├── test_allocation.py # ✅ weights by ticker/sector/industry, empty/zero-total
    │   │   │   ├── test_cost_basis.py # ✅ FIFO realized/unrealized, splits, dividends, fees, mixed-ccy
    │   │   │   ├── test_ingest.py      # ✅ snapshot→opening-BUY, holding upsert, missing-portfolio None (faked provider)
    │   │   │   ├── test_imports.py     # ✅ async pipeline: accept→PENDING, background process→SUCCEEDED, per-batch progress, duplicate 409/override, failure recorded not raised
    │   │   │   ├── test_service.py    # ✅ Read orchestration, XIRR, allocation, offline unpriced tickers, and typed position gaps/provenance — faked providers
    │   │   │   ├── test_holding_analytics.py # ✅ Scoped open/closed XIRR, partial sells/dividends/fees/splits, snapshots/import history, FX, valuation citations, undefined/zero returns
    │   │   │   ├── test_history.py # ✅ Pure typed history reasons and share-replay guards for deleting purchases, sales and splits
    │   │   │   ├── test_history_confirmation.py # ✅ Canonical scoped fingerprints, acknowledgement vs hard blockers, invalid events and changed-history policy
    │   │   │   ├── test_classification.py # ✅ MANUAL protection, partial-profile replacement, failed-refresh preservation, retry safety, and finite cursor sweeps
    │   │   │   ├── test_reconciliation.py # ✅ Pure split inference from confirmed history, ambiguity/rounding guards, and source-matching correction validation
    │   │   │   ├── test_statements.py  # ✅ Robinhood 9-col export: trade/dividend/tax mapping, Activity-Date keying, derived price, money-cell cleaning, option/transfer/split warnings, non-activity CSV rejected
    │   │   │   └── test_xirr.py       # ✅ pinned XIRR (10%/20%/neg, Excel ref), mixed-ccy, error paths
    │   │   ├── providers/         # ✅ SQLAlchemy portfolio provider round-trip (in-memory SQLite)
    │   │   │   ├── test_portfolio_provider.py # ✅ ORM→schema mapping, exact Decimals, feeds calculators
    │   │   │   ├── test_portfolio_writer.py   # ✅ write half: create portfolio, list portfolios, add txns, idempotent holding upsert
    │   │   │   ├── test_statement_import_store.py # ✅ local-disk blob store (round-trip, traversal guard, atomic write) + job lifecycle/checksum lookup
    │   │   │   ├── test_import_recovery.py # ✅ Partial-failure retry ownership, startup reconciliation, corrupt-byte refusal, persisted repair gaps, and exactly-once correction
    │   │   │   ├── test_holding_history.py # ✅ Persisted snapshot origin and matching public history flags, import/unresolved scoping and unknown-scope refusal
    │   │   │   ├── test_transaction_deletion.py # ✅ Scoped stable IDs, durable history invalidation, rollback, dependent-sale/active-import conflicts and retry replay protection
    │   │   │   └── test_history_confirmation.py # ✅ Durable confirmation, untouched origins, stale snapshots, import invalidation and offline lock/concurrent-write coverage
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
    │   │   │   ├── conftest.py        # ✅ Seeded in-memory SQLite (incl. an unclassified holding) + get_session/market-data/profile/statement-storage overrides + AsyncClient fixtures
    │   │   │   ├── test_portfolio_routes.py # ✅ health, summary/txns/holdings/analytics (cost-basis + market values + XIRR status), 200 + 404
    │   │   │   ├── test_holding_analytics_routes.py # ✅ Holding XIRR decimal-string/status/provenance contract, case-insensitive 404s, offline closed positions, snapshots/imports and unrelated price/FX isolation
    │   │   │   ├── test_transaction_deletion_routes.py # ✅ Stable-ID ledger with read-only row origins, scoped deletion conflicts and immediate analytics
    │   │   │   ├── test_history_confirmation_routes.py # ✅ Review/confirm contract, strict acknowledgement, blockers, repair, origins, stale tokens and scoped statuses
    │   │   │   ├── test_ingest_routes.py    # ✅ GET list + POST create/transactions/positions; async import 202→poll→SUCCEEDED→analytics, duplicate 409, 404/422
    │   │   │   ├── test_classification_routes.py # ✅ Single holding GET, nullable MANUAL PATCH, immediate analytics, finite cursor sweeps, safe repeats, and configuration-vs-quota failures
    │   │   │   ├── test_unresolved_routes.py # ✅ Typed import issues, atomic source-matching repairs, cleared gaps, retry errors, and complete-history opt-in
    │   │   │   ├── test_openapi.py    # ✅ Checked-in OpenAPI contract must match the application schema exactly
    │   │   │   └── test_cors.py        # ✅ config-driven CORS: allowed/disallowed origin headers + preflight (OPTIONS)
│   └── integration/           # 🟡 @pytest.mark.integration — real Postgres/pgvector + MCP/Ollama wiring (opt-in)
│       ├── test_postgres_pgvector.py # ✅ connect + CREATE EXTENSION vector + vector column round-trip
│       ├── test_ollama_live.py        # ✅ live Ollama completion + embedding smoke (skips if daemon down)
│       └── test_alphavantage_live.py  # ✅ live hosted AlphaVantage MCP list_tools + quote (skips if unconfigured)
├── scripts/                   # 🟡 Dev utilities — NOT shipped (hatch builds only app/), excluded from the lint gate
│   ├── portfolio_demo_1_2.py  # ✅ End-to-end deterministic-core demo: DB → provider → calculators (in-memory, no infra)
│   ├── import_demo.py         # ✅ Create portfolio → upload broker CSV → analytics over the real app (in-memory; dry-runs your own export)
│   └── ollama_healthcheck.py  # ✅ Ollama connectivity/latency diagnostic (reachability, installed models, timed completion)
└── app/
    ├── main.py                # ✅ FastAPI app factory + lifespan (DB engine on state, interrupted imports → FAILED) + /health; CORS and v1 router
    ├── core/                  # 🟡 Cross-cutting infra (NOT business logic)
    │   ├── config.py          # ✅ Pydantic Settings — env-driven (base/supported currency, DB URL, AI provider, CORS origins)
    │   ├── database.py        # ✅ Async engine (pooled + pre_ping for Postgres) + session factory + declarative Base; missing optional DB drivers raise an actionable "sync this extra" error
    │   ├── logging.py         # ⬜ Structured logging config
    │   ├── security.py        # ⬜ Single-user local gate (optional API_ACCESS_KEY) — no multi-tenant
    │   ├── currency.py        # ✅ FX normalization seam (Money/FxRate/FxRateTable) — USD now, INR-ready
    │   └── exceptions.py      # ⬜ App-wide error types + handlers
    ├── api/                   # 🟡 HTTP layer only (thin controllers, no business logic)
    │   ├── deps.py            # ✅ Typed dependencies for portfolio analytics, atomic history review/confirmation, ledger reads/deletion, ingest/import and optional market data
    │   └── v1/
    │       ├── router.py      # ✅ Aggregates all v1 routes
    │       └── routes/        # 🟡 portfolio.py ✅; research.py, documents.py, marketdata.py, workspace.py ⬜
    │           └── portfolio.py   # ✅ Portfolio/import routes, stable-ID ledger GET/DELETE, holding history review/confirmation/detail/XIRR, classification and unresolved repair
    ├── providers/             # 🟡 Strongly-typed abstraction interfaces (§2) — the ONLY I/O boundary
    │   ├── base.py            # ✅ Typed PortfolioProvider, HoldingAnalyticsProvider, HoldingHistoryProvider, TransactionLedgerProvider, PortfolioWriter and StatementImportStore protocols
    │   ├── portfolio_provider.py  # ✅ Active ledger/row origins, atomic locked reviews and confirmations, canonical state mapping, classification and guarded scoped tombstones
    │   ├── statement_storage.py   # ✅ StatementStorage Protocol — raw blob put/get, kept OUT of the relational DB (local disk now, S3 later)
    │   ├── statement_import_store.py # ✅ Import state/progress, owned batches, startup recovery, tombstone-safe retry cleanup, unresolved items and atomic corrections
    │   ├── marketdata_provider.py  # ✅ MarketDataProvider Protocol — quotes/profiles/statements (cache-first)
    │   ├── competitor_matrix_engine.py
    │   ├── sec_provider.py
    │   ├── news_streaming_engine.py
    │   └── document_provider.py
    ├── portfolio/             # 🟡 Ledger, allocation weights, investor returns (XIRR), valuations (pure Python)
    │   ├── models.py          # ✅ SQLAlchemy ledger/import provenance and tombstones plus holding-scoped confirmation tokens/timestamps
    │   ├── schemas.py         # ✅ Separate transaction input/origin-bearing ledger read models, typed review/confirmation/snapshots, history reasons and analytics/import/correction carriers
    │   ├── service.py         # ✅ Active-ledger portfolio analytics with per-position history/classification diagnostics, unpriced tickers and freshly read allocation labels
    │   ├── history.py         # ✅ Pure canonical review fingerprints, acknowledgement/hard-blocker policy, confirmation invalidation and financial/share replay validation
    │   ├── holding_analytics.py # ✅ Ticker-only XIRR with shared effective-history policy, price/FX/provenance guards and no quote dependency for closed holdings
    │   ├── ingest.py          # ✅ Write orchestration: manual trades + current-holding snapshots (→ internally marked synthetic opening BUY) behind the PortfolioWriter seam
    │   ├── imports.py         # ✅ Accept/checksum/store → claimed background batches → terminal state, retained-byte retry verification, and typed source correction orchestration
    │   ├── classification.py  # ✅ MANUAL-protected company-profile backfill; refresh replaces taxonomy/provenance, finite cursor sweeps, and typed per-ticker retryable failures
    │   ├── reconciliation.py  # ✅ Pure conservative split inference for confirmed full history and source-matching validation for user corrections
    │   ├── statements.py      # ✅ Content-validated Robinhood CSV parser → typed ledger events, warnings, and structured unresolved source issues; no guessed transfer cost basis
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
    ├── storage/               # ✅ Blob adapters — raw uploaded files, kept out of the relational DB
    │   └── local_disk.py      # ✅ LocalDiskStatementStorage — atomic temp-then-replace writes, path-traversal guard, thread-offloaded I/O
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
├── vitest.setup.ts            # ✅ jest-dom + MSW lifecycle, native Node abort constructors for fetch, ResizeObserver stub
├── .env.local.example         # ✅ NEXT_PUBLIC_API_BASE_URL + NEXT_PUBLIC_API_MOCKING
├── .gitignore                 # ✅ node_modules/.next/env/coverage/generated worker
├── README.md                  # ✅ Runbook (install, dev, test, typegen, mock-vs-live, money model)
├── Dockerfile                 # ⬜ Frontend container image — DEFERRED (post live-wiring); local dev runs via `npm run dev`
├── public/
│   └── mockServiceWorker.js   # 🟡 MSW browser worker (generated by `npx msw init`, git-ignored)
└── src/
    ├── app/                   # ✅ App Router
    │   ├── layout.tsx         # ✅ Root layout: globals, terminal chrome (Nav), Providers
    │   ├── holdings/page.tsx # Dedicated reported snapshots
    │   ├── ledger/page.tsx # Ledger analytics and manual entry
    │   ├── imports/page.tsx # Brokerage-selected imports
    │   ├── settings/page.tsx # Account metadata settings
    │   ├── page.tsx           # ✅ automatic selected-account overview mount point
    │   ├── portfolios/[id]/holdings/[ticker]/page.tsx # ✅ Validated, bookmarkable URL-scoped holding detail route
    │   ├── providers.tsx      # ✅ Client bootstrap; mounts MSW mock (ssr:false) + PortfolioSelectionProvider
    │   └── globals.css        # ✅ Tailwind layers + light/dark design tokens
    ├── components/
    │   ├── ui/                # ✅ shadcn-style primitives: card, badge, skeleton, table, button, input, select, label, progress, dialog
    │   ├── shared/            # ✅ states.tsx — loading / error / empty blocks (honest "—", no fake 0)
    │   ├── portfolio/         # ✅ views
    │   │   ├── portfolio-summary.tsx       # ✅ Headline stats and status-driven XIRR guidance; unavailable values stay "—"
    │   │   ├── allocation-chart.tsx        # ✅ Linked wedge/legend previews and pinning with typed current-holding lists, backend portfolio weights and partial-pricing notice
    │   │   ├── allocation-section.tsx      # ✅ Portfolio/refresh-keyed shared analytics+holdings reads, nonblocking list errors and stale-generation isolation
    │   │   ├── transaction-ledger.tsx      # ✅ Stable-ID/origin-labeled ledger with provenance-aware confirmed deletion and scoped refresh
    │   │   ├── holdings-table.tsx          # ✅ Holding links/history diagnostics and classification with suggestions shared from full holdings
    │   │   ├── holding-history.tsx         # ✅ Shared history diagnostics and exhaustive typed reason labels
    │   │   ├── holding-history-review.tsx  # ✅ Accessible snapshot review, locked-ticker missing-event entry, explicit confirmation and stale-token recovery
    │   │   ├── ledger-origin.ts           # ✅ Read-only origin labels distinguishing observed events, synthetic snapshots and unverified legacy rows
    │   │   ├── holding-detail.tsx          # ✅ URL-scoped history/XIRR/ledger and nonblocking same-portfolio classification suggestions refreshed after writes
    │   │   ├── holding-classification-cell.tsx # ✅ Per-field PATCH combobox with explicit Save/Cancel, null clearing and preserved drafts
    │   │   ├── classification-combobox.tsx # ✅ Typed per-field suggestion normalization and accessible keyboard/mouse manual selection with unique list IDs
    │   │   ├── holding-data-gaps.tsx       # ✅ Readable typed gap warnings, separate from unavailable provider data
    │   │   ├── classify-holdings-button.tsx # ✅ Abortable cursor sweep with classified/unresolved/failure summaries and 503 configuration guidance
    │   │   ├── watchlist.tsx               # ✅ Add/remove tickers (localStorage-backed)
    │   │   ├── portfolio-selector.tsx      # ✅ App-shell picker over GET /portfolios; "create one" when empty
    │   │   ├── create-portfolio-dialog.tsx # ✅ POST /portfolios then auto-select
    │   │   ├── add-position-form.tsx       # ✅ POST /positions; cost basis = exactly one of per-share/total (422-proof); explains XIRR trade-off
    │   │   ├── manual-transaction-form.tsx # ✅ Type-aware transaction input with optional locked ticker, unique control IDs, abort guards and preserved error drafts
    │   │   ├── import-panel.tsx            # ✅ CSV upload/poll and refreshable import history with retry-safety label
    │   │   └── dashboard.tsx               # ✅ Route-owned panels; imports/settings have dedicated pages, overview retains automatic view policy
    │   ├── app-shell/         # ✅ nav.tsx — top bar + portfolio picker + light/dark toggle
    │   ├── research/          # ⬜ Ticker workstation, competitor matrix, thesis canvas
    │   └── workspace-panel/   # ⬜ Context-aware side panel (streaming tokens)
    ├── hooks/                 # ✅ Data + UI state hooks
    │   ├── use-api-resource.ts         # ✅ Generic async state (loading/error/success), stale-response guard
    │   ├── use-portfolio.ts            # ✅ Typed endpoint hooks including single-holding reads, per-holding XIRR, and version-token refetch
    │   ├── use-portfolio-selection.tsx # ✅ Selection context: list + selected id (localStorage) + dataVersion refetch token
    │   ├── use-import-job.ts           # ✅ Poll one import job to a terminal state (self-scheduling; no leaked intervals)
    │   └── use-watchlist.ts            # ✅ localStorage watchlist (normalized, de-duplicated)
    ├── lib/                   # ✅ Client-side infra
    │   ├── env.ts             # ✅ Validated public env (API base URL, mock flag)
    │   ├── api-client.ts      # ✅ Typed REST client including atomic holding-history GET/POST, scoped bodyless DELETE and ApiError
    │   ├── decimal.ts         # ✅ Float-free Decimal-string parse/round/scale helpers
    │   ├── format.ts          # ✅ money/percent/quantity formatting; DASH for null/unpriced
    │   └── utils.ts           # ✅ cn() class-merge helper
    ├── mocks/                 # ✅ MSW mock layer (contract-shaped)
    │   ├── fixtures.ts        # ✅ Typed origin-bearing ledger IDs and holding history seed data
    │   ├── state.ts           # ✅ Mutable write/import/classification/deletion state with scoped snapshot tokens, confirmation and invalidation
    │   ├── handlers.ts        # ✅ Contract-shaped portfolio/import writes, guarded history review/confirmation and scoped DELETE mocks
    │   ├── server.ts          # ✅ Node server for Vitest (msw/node)
    │   ├── browser.ts         # ✅ Browser worker (msw/browser) — client-only
    │   └── mock-bootstrap.tsx # ✅ Client-only worker starter (loaded via ssr:false)
    ├── types/                 # ✅ Contract types
    │   ├── api.ts             # ✅ GENERATED OpenAPI including typed review/confirmation and required read-only transaction origins
    │   └── domain.ts          # ✅ Distinct ledger input/output, origin, history reason and review/confirmation aliases
    └── __tests__/             # ✅ Vitest + RTL specs
        ├── lib/               # ✅ Existing decimal/format/client/holding/deletion specs plus holding-history-api.test.ts for review/confirmation scope, payloads and errors
        ├── hooks/             # ✅ use-import-job (poll-to-terminal, stop-on-unmount)
        └── components/        # ✅ Existing panel/holding/deletion specs plus holding-history-review.test.tsx for review/repair/confirm, cancellation/stale reads and refresh; ledger-origin.test.tsx for origin labels and snapshot-safe deletion
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
- **Market data is opt-in:** the provider is built only when **both** `ALPHAVANTAGE_MCP_URL` and `ALPHAVANTAGE_API_KEY` are set (the URL has a default, so the key is the real switch). Unconfigured means market values, allocation weights, sector/industry backfill, and the money-weighted return are unavailable — reported explicitly (`unpriced_tickers`, `UNPRICED_POSITIONS`, HTTP 503) rather than faked.
- **Uploaded statements are files, not rows:** `STATEMENT_STORAGE_DIR` holds raw broker exports (git-ignored); the database keeps only metadata + a pointer. `IMPORT_BATCH_SIZE` / `IMPORT_MAX_STORED_WARNINGS` tune the async import pipeline.

---

## Testing Conventions

- **Tests ship with code, every turn** (`AGENTS.md` §11) — a change is incomplete without them.
- **Backend:** `pytest` + `pytest-asyncio` + `pytest-cov`. `backend/tests/` mirrors `backend/app/` one-to-one; provider boundaries are mocked in unit tests. Integration tests are marked `@pytest.mark.integration` and excluded from the fast default run.
  - Run: `uv run pytest` · integration: `uv run pytest -m integration` · coverage: `uv run pytest --cov=app`.
  - `tests/api/test_openapi.py` guards the published contract: regenerate `backend/openapi.json` from `create_app().openapi()` after API/schema changes (command in `backend/README.md`).
- **Frontend:** Vitest + React Testing Library, specs co-located under `src/__tests__/`. Run: `npm run test`.
- **What to assert for AI code:** structured output schemas, tool routing, LangGraph state transitions, and citation presence/shape — never exact LLM wording.

---

## Allocation Interaction Regression Inventory

- `frontend/src/__tests__/components/allocation-chart.test.tsx` — Real Recharts SVG hover/click paths, legend focus/Enter/Space/Escape, clear/focus restoration, separate chart states and IDs, keyed data reconciliation, exact decimal display, empty/no-arc states and reduced-motion styling.
- `frontend/src/__tests__/components/allocation-section.test.tsx` — Contract-shaped MSW analytics reads, portfolio-keyed selection isolation, stale-response dismissal, token refresh, API failure recovery and unavailable allocations.
- `frontend/README.md` documents read-only selection semantics, theme/accessibility choices, the installed Recharts v2 API seam and network-refresh pin resets.

---

## Frontend UI Regression Inventory

- `frontend/src/__tests__/components/history-confirm-dismissal.test.tsx` — Table/detail confirmation waits for server success, dismisses and restores focus, refreshes XIRR, reopens persisted confirmation, and stays open on failures.
- `frontend/src/__tests__/components/button-labels.test.tsx` — Explicit Title Case button text and accessible names across the dashboard, review, creation, classification and deletion controls without changing ticker/data casing.
- `frontend/src/components/portfolio/holding-history-review.tsx` closes only after successful confirmation; repairs and stale/error recovery retain the dialog. Other frontend action components use explicit Title Case button labels rather than CSS text transforms.
- `frontend/src/__tests__/components/classification-suggestions.test.tsx` — Field-specific trimmed/deduplicated/sorted suggestions, table/detail other-holding values, shared reads, keyboard/mouse/ARIA behavior, scope/delayed reads, refreshed options, failure drafts, blank clears and cancellation.
- `frontend/src/__tests__/components/holdings.test.tsx` and `dashboard.test.tsx` query classification editors by their combobox role while retaining existing draft/history/allocation regressions.
- `frontend/README.md` documents suggestion matching, explicit selection vs save, nonblocking detail reads and the new frontend file map.
- `frontend/src/__tests__/components/dashboard.test.tsx` — Accessible category buttons and meaningful detail summaries, click/Enter/Space pinning, exact Clear Selection action, requested-portfolio scope and inline-edit allocation refresh.
- `frontend/src/__tests__/components/button-labels.test.tsx` — Fixed-action Title Case checks classify data-driven category controls separately; independent uppercase/lowercase/mixed-case category assertions preserve API spelling in both donuts and require exact Clear Selection labels.

---

## Allocation Holding Breakdown Delivery Inventory

No files or directories added; backend, contract, hooks, client and generated types
remain unchanged. Exact modified slice paths and responsibilities:

- `frontend/src/components/portfolio/allocation-chart.tsx` — Joins open analytics
  positions to exact classification metadata, groups both dimensions once, and
  displays all category members with backend ticker weights, missing/unpriced
  statuses, partial-denominator guidance and accessible bounded scrolling.
- `frontend/src/components/portfolio/allocation-section.tsx` — Shares one holdings
  read across both charts per portfolio/refresh generation; keys both resources to
  prevent old membership appearing alongside refreshed analytics.
- `frontend/src/__tests__/components/allocation-chart.test.tsx` — Adds actual SVG
  membership/highlight, keyboard pin/preview restoration, independent dimensions,
  exact null/blank/literal UNCLASSIFIED, closed/no-ledger exclusion, missing/unpriced
  decimal weights, empty membership and complete 100-entry scroll-list coverage.
- `frontend/src/__tests__/components/allocation-section.test.tsx` — Adds shared-read
  count, loading/error/recovery, same-generation membership, delayed scope/version
  response isolation and runtime analytics-404 coverage using typed MSW responses.
- `frontend/src/__tests__/components/dashboard.test.tsx` — Verifies a successful
  inline classification edit moves the ticker between refreshed category lists;
  its initial exact PLTR link query allows 3s for parallel-worker startup.
- `frontend/src/__tests__/components/button-labels.test.tsx` — Preserves every
  Title Case/data-casing assertion; only the initial exact AAPL review-button
  query allows 3s for portfolio selection followed by panel loading.
- `README.md` — Describes holding-level donut inspection and priced-subset limits
  without changing setup or environment requirements.
- `frontend/README.md` — Documents API consumption, exact grouping, loading/error
  and refresh semantics, keyboard scrolling, non-atomic GET limitations and the
  narrow initial-loading wait policy with actual validation results.
- `PLAN.md` — Tracks roadmap scope and a concise delivered-feature summary; commit history lives in Git and delivery policy in `AGENTS.md`.
- `STRUCTURE.md` — Maintains the updated allocation responsibilities and this exact
  delivery inventory.

Validation follow-up: affected-file tests passed 3/3; the unchanged full suite
passed 204/204 (12.77s), consistent with intermittent default-1s startup waits
under parallel jsdom/MSW load rather than a reproducible allocation regression.
Only the two reported initial loading queries now have a 3s maximum retry budget;
no assertion was removed, skipped or loosened, and production code, handlers,
hooks and Vitest configuration were not changed in this follow-up.
Two consecutive post-fix `npm test -- --reporter=dot` runs passed 204 tests in
27 files (13.88s and 12.45s), plus ESLint and TypeScript (exit 0). Independent
parent validation also passed 204 frontend tests (12.63s), lint and typecheck;
backend passed 433 tests (3 integration tests deselected), Ruff and mypy for
50 source files. This slice ships with tests/docs in a local Conventional Commit.
Live browser/API integration was not exercised. No dependency or API contract
change; OpenAPI's undocumented runtime analytics 404 remains noted in docs.

## Account/security and reported-valuation foundation inventory

Additive backend-only slice; frontend and legacy ledger analytics are unchanged.
New active files (paths relative to repository root):

```text
backend/
  app/
    portfolio/accounts.py                  # Typed account/security/snapshot contracts, pure currency policy, canonical hashes, exact reported totals and service orchestration
    providers/account_provider.py          # AccountProvider protocol and SQLAlchemy I/O with composable atomic transactions, scoped identities and immutable date snapshots
    api/v1/routes/accounts.py              # Thin metadata PATCH, shared securities POST/GET and separate reported valuations POST/GET
  migrations/versions/0009_account_valuations.py # Adds account metadata plus securities/security_aliases/account_valuations/account_valuation_positions; ledger rows untouched
  tests/
    unit/portfolio/test_accounts.py         # Pure hashing, exact totals, null basis/returns, provenance, validation and mocked provider-boundary orchestration
    unit/providers/test_account_provider.py # Offline project-fixture persistence, aliases/fund classes, idempotency/conflicts, historical reads and composed rollback
    api/test_account_routes.py             # Account identifier strings, immutable security identities, decimal/null/status/provenance contracts and no legacy ledger/analytics side effects
```

Updated active files:

- `backend/app/portfolio/models.py`: account metadata on portfolios and four
  isolated relational security/valuation tables; legacy holdings/ledger unchanged.
- `backend/app/portfolio/schemas.py`: `AccountType` and backward-compatible
  defaulted/nullable account metadata in `PortfolioCreate`/`PortfolioSummary`.
- `backend/app/providers/portfolio_provider.py`: persists and maps metadata on
  existing portfolio create/list/read APIs, without altering ledger policy.
- `backend/app/api/deps.py` and `backend/app/api/v1/router.py`: compose/register
  the account provider/service/routes on the existing request-scoped DB session.
- `backend/tests/test_migrations.py`: 0009 upgrade/downgrade legacy-row preservation
  and scoped Alembic type/constraint drift checks for new tables and portfolios;
  existing all-model column drift coverage remains active. Pre-existing SQLite
  NUMERIC/text differences in untouched legacy tables are outside the new check.
- `backend/openapi.json`: generated account metadata, shared securities and
  valuation-only request/response contracts, including typed error variants.
- `backend/README.md` and `README.md`: migration 0009 prerequisite, runnable Swagger
  examples and explicit separate-view/non-additive reported snapshot semantics.

Reported views never write BUY events or infer acquisition dates. Snapshot-only
money-weighted returns are null with typed `VALUATION_ONLY` history status;
availability is `AVAILABLE`, `PARTIAL`, or `EMPTY`. Immutable historical snapshots
are unique by portfolio/date, with domain-generated canonical content hashes.
No Vanguard parser, private source files, new dependencies or frontend changes are
included in this foundation. `PLAN.md` records the approved resumable delivery
roadmap, financial semantics, acceptance tests and sourced free-MCP shortlist.

Validation: `uv run pytest` passed 491 tests (3 integration tests deselected);
`uv run ruff check .` passed; `uv run mypy` passed for 53 source files. Tests use
only fictitious fixtures and disposable SQLite databases; no external services or
live database were used. Editor diagnostics were run on every slice file: no errors,
with two pre-existing warnings in untouched legacy provider logic. The initial new
module indexing error cleared on recheck. All existing API path contracts and old
schema properties were compared against HEAD and preserved. No staging or commits
were performed.

## Vanguard retirement import slice 2a inventory

Backend-only import core delivered; frontend/Robinhood/legacy analytics are unchanged.
New active files (relative to repository root):

```text
backend/
  app/
    portfolio/vanguard.py                       # Frozen typed source/review/activity contracts, pure two-section parsing, canonical alias/event hashes, reconciliation and state-bound review policy
    portfolio/vanguard_service.py               # Bounded synchronous preview/commit orchestration with typed provider/storage seams and retained-byte checksum/reparse verification
    providers/retirement_import_provider.py     # RetirementImportProvider protocol and SQLAlchemy read-only review, locked atomic ownership/security/snapshot/activity writes and persisted history/detail/activity reads
    api/v1/routes/retirement.py                  # Thin multipart preview/strict confirmation and scoped retained import/activity HTTP routes
  migrations/versions/0010_vanguard_imports.py  # Adds retirement_imports and retirement_activity with checksum uniqueness, ownership FKs and indexed nonunique fingerprints
  tests/
    vanguard_fixtures.py                        # Entirely fictitious Python source-export builders shared across offline tests; no tracked CSV
    unit/portfolio/test_vanguard.py             # Pure parser/financial/hash limits and statuses plus mocked provider/storage orchestration
    unit/providers/test_retirement_import_provider.py # Project SQLite fixture persistence, exact decimals, multiplicity, overlap/staleness, retained closed funds and injected atomic rollback/retry tests
    api/test_retirement_routes.py               # Multipart preview/commit/read contracts, strict true, typed null/decimal/provenance/status errors and OpenAPI seam assertions
```

Updated files:

- `backend/app/portfolio/models.py`: isolated retirement ownership/activity mapped
  tables; parsed typed facts/diagnostics are serialized text, never raw file bytes.
- `backend/app/api/deps.py`: request-scoped Vanguard provider/storage composition.
- `backend/app/api/v1/router.py`: registers separate retirement route group.
- `backend/tests/test_migrations.py`: 0010 upgrade/downgrade and scoped full Alembic
  schema drift/constraint coverage; existing all-model column guard stays active.
- `backend/openapi.json`: generated `RetirementPreview`, `RetirementImport`,
  `ObservedActivity`, typed diagnostics/reconciliation and multipart/error schemas.
- `backend/README.md`: head 0010 prerequisite, runnable Swagger workflow, exact
  schemas/nullability, conservative overlap policy and remaining API limitations.
- `README.md`: migration prerequisite and separate backend retirement workflow.
- `PLAN.md`: slice 2a delivered backend import core checked off; post-import security
  metadata/mapping amendment required before slice 4, not a 2a blocker; 2b unchanged.
- `STRUCTURE.md`: this precise delivery inventory.

Preview is stateless/read-only. Commit binds unassigned raw account ID/custodian,
creates UNKNOWN/null-ticker securities for unseen plan-scoped aliases, and commits
whole valuation/activity/import ownership atomically. Both supported source codes
retain independent reported amounts/prices/units; unknown codes are visible and
block commit. Partial history is not an opening lot or performance history. All
returned decimals are strings with retained source lines/checksums/references.
Checksum blobs stay behind StatementStorage, outside the DB/Git; failed DB commits
may leave unreachable blobs only. Different-file fingerprint overlap is refused,
while same-file multiplicity is preserved. Same-date snapshots retain strict
foundation provenance/content conflict semantics.

Required future work before slice 4, not a slice 2a blocker: securities POST is
immutable and refuses existing aliases (409). Explicit pre-import mappings and
stable UNKNOWN/null-ticker securities are approved delivered import scope.
Post-import security metadata amendment, ticker identity confirmation/update and
alias remapping need a separately approved schema/API slice before look-through.
No speculative endpoint or shared identity contract change was introduced.
Live PostgreSQL contention and frontend integration remain unexercised. No external
calls, real CSV, live DB, staging or commits were used.

Validation from backend: `uv run pytest` passed **580 tests** (3 integration tests
deselected), `uv run ruff check .` passed and `uv run mypy` passed (57 source files).

## Retirement dashboard slice 2b inventory
Frontend-only delivery consumes the published slice 1/2a OpenAPI seam. New files
(paths relative to repository root):
- `frontend/src/hooks/use-retirement.ts`: abortable generation-keyed reads and single active scoped writes.
- `frontend/src/components/portfolio/account-settings.tsx`: actual account GET, explicit metadata Save/Cancel, nullable clears and leading-zero drafts.
- `frontend/src/components/portfolio/retirement-import-panel.tsx`: separate Vanguard preview/confirmation, source diagnostics, retained reviews/history/activity.
- `frontend/src/components/portfolio/reported-holdings.tsx`: primary reported snapshot total, numeric security-name join, null/partial/empty provenance.
- `frontend/src/mocks/retirement-fixtures.ts`: wholly fictitious fixed CSV bytes and typed preview/activity/valuation/security fixtures.
- `frontend/src/mocks/retirement-handlers.ts`: contract-shaped account reads/writes and fixed-demo retirement persistence, no arbitrary parsing claim.
- `frontend/src/__tests__/lib/retirement-api.test.ts`: exact multipart/options/true, typed errors, persistence, scope and mock refusal.
- `frontend/src/__tests__/lib/retirement-transport.ts`: test-only jsdom/Node CSV multipart and File-brand bridge, restored after each test.
- `frontend/src/__tests__/components/account-settings.test.tsx`: accessible metadata saves, zero-prefixed IDs, null clearing, drafts and stale/cancel guards.
- `frontend/src/__tests__/components/retirement-import.test.tsx`: full dashboard import refresh, review invalidation, conflicts/errors/history, abort and double-submit guards.
- `frontend/src/__tests__/components/reported-holdings.test.tsx`: identity/null/decimal/partial/empty fidelity, default view and stale portfolio isolation.
Updated files:
- `frontend/src/types/api.ts`: regenerated from actual `backend/openapi.json`; no manual edits.
- `frontend/src/types/domain.ts`: separate default-optional request aliases and strict reads, plus account/security/valuation/retirement/activity aliases.
- `frontend/src/lib/api-client.ts`: metadata PATCH, shared security and reported snapshot GETs, multipart preview/strict confirmation and retained import/activity reads.
- `frontend/src/components/portfolio/dashboard.tsx`: account-keyed view boundary, automatic reported selection, explicit Ledger Analytics view and sibling/selector refresh.
- `frontend/src/mocks/state.ts`: resettable scoped retirement persistence and immutable metadata replacement; existing mock creation fills default response metadata.
- `frontend/src/mocks/handlers.ts`: registers retirement handlers for browser and test use.
- `frontend/src/mocks/fixtures.ts`: required defaulted account_type on four legacy summaries; ledger values unchanged.
- `frontend/src/__tests__/components/button-labels.test.tsx`: adds five new fixed dashboard actions to the exhaustive Title Case/accessibility inventory.
- `README.md`: runnable account-settings, preview/confirm and reported-holdings click path, migration 0010 prerequisite and fixed-demo/live limits.
- `frontend/README.md`: precise consumed REST seam, request/read distinctions, cancellation/drafts/refresh semantics, exact file map and validation evidence.
- `PLAN.md`: delivered slice 2b status and scope; future identity amendment is not an import-workflow blocker.
- `STRUCTURE.md`: this exact delivery inventory; pre-existing trees and backend inventories unchanged.
Consumed contract: `backend/openapi.json`, with existing portfolio GET/list;
PATCH `/api/v1/portfolios/{portfolio_id}/account`; GET `/api/v1/securities`;
GET `/api/v1/portfolios/{portfolio_id}/valuations`; POST
`/api/v1/portfolios/{portfolio_id}/retirement-imports/preview` and
`/api/v1/portfolios/{portfolio_id}/retirement-imports`; GET that import collection,
its `/{import_id}` detail and `/api/v1/portfolios/{portfolio_id}/account-activity`.
Preview/commit use multipart file bytes and explicit date/currency/history options;
commit adds the preview token and strict `confirmed=true`. Request aliases retain
default omission semantics separately from strict response types. No backend or
contract files are changed by slice 2b.
Reported and legacy ledger values are never combined. Snapshots remain valuation-only;
no frontend financial calculations, ticker guesses, acquisitions or returns are added.
Mock mode accepts only the exported fictitious fixture, not arbitrary user CSVs.
Success refreshes snapshot, names, account/selector metadata, history and activity;
source/date/options/refresh changes invalidate reviews without discarding drafts.
Stable UNKNOWN/null-ticker securities support the delivered workflow now;
post-import identity amendment is future look-through work, not a slice 2b blocker.
Validation from the implementation: typegen succeeded; full npm test passed 235/235
in 31 files; npm run lint and npm run typecheck exited 0. No backend executable
changes, dependencies, private fixtures, staging or commits. Live services/browser
integration were not exercised.

Final documentation review: HEAD prefix byte equality, zero U+FFFD in all four
delivery docs, tracked/new-file whitespace checks and docs diagnostics passed.
Frontend reruns: lint/typecheck passed; both full test runs had 234 passed and
one focus-restoration failure at history-confirm-dismissal.test.tsx:68. The
isolated file also failed that assertion (5 passed, 1 failed). No executable
files changed during this review; this regression is reported, not hidden.

## Retirement dashboard focus/refetch follow-up

Exact files changed by this follow-up (prior uncommitted slice work is preserved):
- `frontend/src/components/portfolio/dashboard.tsx`: keeps only the account-keyed
  last resolved default-view boolean across refetches; renders legitimate ledger
  panels in a stable sibling slot through valuation loading/errors. Reported data
  still renders only from the current successful request generation. Portfolio
  changes reset policy, explicit view choice, drafts and ledger component identity.
- `frontend/src/components/ui/dialog.tsx`: focus acquisition/restoration uses layout
  effect setup/cleanup so dismissal restores the connected trigger in the DOM
  commit, not a later passive-effect flush. Keyboard/dismissal behavior is unchanged.
- `frontend/src/__tests__/components/dashboard-account-refresh.test.tsx`: four
  contract-shaped MSW regressions cover original-trigger identity/focus after
  confirmation, sibling refresh, persisted confirmation, draft preservation through
  errors/recovery, no stale/zero/empty reported fallback, explicit ledger selection,
  account remounting and aborted older request-generation isolation.
- `frontend/src/__tests__/components/dialog-focus.test.tsx`: two commit-time focus
  regressions cover button/Escape dismissal, initial modal focus and restoration.
- `STRUCTURE.md`: this inventory and validation record.

The previously reported `history-confirm-dismissal.test.tsx:68` failure initially
reproduced neither in isolation (6/6 passed) nor in the unchanged full suite
(235/235 passed, 31 files). The new dashboard test then deterministically failed
with focus on body because reported-resource loading unmounted the ledger trigger.
After the dashboard fix, a full run reproduced the original **detail** focus failure
(238 passed, 1 failed), which cannot be caused by Dashboard. The shared Dialog's
passive cleanup allowed its DOM to disappear before focus restoration. New
layout-phase observations independently reproduced body focus on dismissal (2/2
failed before the primitive fix); switching that focus lifecycle to a layout effect
fixed both commit-time regressions. The original history-confirm-dismissal tests
remain completely unchanged: no skipped assertions, wait-budget or runner changes.

Final validation from `frontend/`:
- Focused `npm test -- src/__tests__/components/dialog-focus.test.tsx src/__tests__/components/dashboard-account-refresh.test.tsx src/__tests__/components/history-confirm-dismissal.test.tsx`: **12/12 passed**, 3 files.
- First full run after both fixes: **240 passed, 1 failed** because the existing
  button-labels test exceeded its 5000ms whole-test limit; no test/config changes
  were made to mask that timeout.
- Consecutive final full runs: `npm test -- --reporter=dot` **241/241 passed in 33
  files** (23.76s), then `npm test` **241/241 passed in 33 files** (24.58s).
- `npm run lint` and `npm run typecheck`: exit 0.
- Editor diagnostics checked every follow-up file: no errors; Dialog retains the
  pre-existing Next.js TS71007 warning for its unchanged `onClose` callback prop.
- `git diff --check`: passed (only existing CRLF normalization notices).

Consumed seam remains existing typed portfolio/valuation/security GETs and scoped
holding-history GET/POST from `backend/openapi.json`; no contract/type regeneration,
backend code, financial calculations, dependencies, staging or commits changed.
`use-retirement.ts` generation guards are unchanged. README/PLAN semantics and run
steps are unchanged, so those documents were not edited by this follow-up. Live
browser/API integration was not exercised.

## Button-label timeout follow-up

Exact follow-up paths:
- `frontend/src/__tests__/components/button-labels.test.tsx`: splits the single
  dashboard workflow into independent fixed-action inventory, watchlist ticker,
  creation dialog, loaded history dialog, classification editor and deletion dialog
  cases. Shared render/storage cleanup isolates each case; dialog queries are scoped.
  Every existing assertion is retained, including exhaustive accessible names,
  allocation decimal formatting, ticker/classification casing and the unchanged
  standalone uppercase/lowercase/mixed-case category regression. Existing focus
  regression files, production code and global/per-test timeouts are unchanged;
  the existing initial loaded-data query retains its 3s maximum retry budget.
- `STRUCTURE.md`: this inventory and validation evidence.

The parent reproduced the original combined case exceeding 5000ms (240 passed,
1 failed), without a matcher failure. This follow-up addresses the shared whole-test
budget rather than retrying that case until lucky. No validation command failed
following the split:
- `npm test -- src/__tests__/components/button-labels.test.tsx`: 7/7 passed;
  cases took 71-831ms (8.59s command duration).
- Two consecutive `npm test` runs: 246/246 passed in 33 files (20.77s, 19.65s).
  The slowest split case took 1962ms and 1691ms respectively, below the unchanged
  5000ms per-test budget. Full logs: `$env:TEMP\asset-button-split-full-1.log`
  and `$env:TEMP\asset-button-split-full-2.log`.
- `npm run lint` and `npm run typecheck`: exit 0.

Consumed seam remains the published `backend/openapi.json` via existing typed
REST client and contract-shaped MSW handlers: portfolio/account, valuation/security,
ledger/holdings/analytics, holding-history and retirement-history/activity reads.
No API/schema/typegen changes, dependencies, backend edits, staging or commits.
README/PLAN setup and feature semantics are unchanged; no updates are required.

## Dedicated portfolio pages delivery
New frontend components:
- `frontend/src/components/app-shell/portfolio-links.tsx`: account-preserving feature links with active-page semantics.
- `frontend/src/components/portfolio/portfolio-boundary.tsx`: URL query synchronization, account-keyed loading/empty states and shared refresh boundary.
- `frontend/src/components/portfolio/imports-page.tsx`: Robinhood/Vanguard selector mounts one existing import form and links to results.
New frontend test files under `src/__tests__/components/`:
- `feature-pages.test.tsx`: route mounts, active links, TAXABLE label/value, import refresh/errors and account/brokerage/navigation isolation.
- `route-harness.tsx`: shared route-aware layout/provider mounting for regression tests.
- `router-state.ts`: deterministic test-only Next navigation state.
Updated layout/Nav provide responsive persistent navigation and a skip link.
Account Settings labels TAXABLE as Taxable Brokerage. Holding detail returns to
Ledger Analytics. Existing dashboard, button-label, account-refresh, holdings,
history-deletion/review, reported-holdings and retirement-import tests target their
owning routes while preserving history/focus/financial assertions. Both import forms,
OpenAPI, generated types, dependencies and backend executable code are unchanged.
Root/frontend README document the new pages and import click path; PLAN marks scope
delivered. Independent checks: 270 frontend tests in 34 files, lint/typecheck passed;
580 backend tests passed, 3 live integration tests deselected, Ruff passed, mypy
passed for 57 source files. Delegate production build passed. Live browser/backend
integration was not exercised.

## Chromium browser foundation (slice 1)

New active files:
```text
frontend/
  playwright.config.ts          # Own mock-only loopback Next server, desktop/narrow Chromium, failure artifacts and HTML reporter
  e2e/
    fixtures.ts                 # Real browser health checks, MSW response verification and narrowly recorded missing-favicon 404
    navigation.spec.ts          # Actual route/active-link clicks, persisted portfolio/query selection and exclusive brokerage forms
```

Updated files and responsibilities:
- `frontend/package.json` / `frontend/package-lock.json`: npm-pinned Playwright and
  headless/headed/UI/debug/report/Chromium-install commands; Vitest scripts unchanged.
- `frontend/next.config.ts`: `FRONTEND_E2E=1` selects `.next/e2e` to avoid the ordinary
  dev output/lock; default runtime configuration is unchanged.
- `frontend/tsconfig.json`: includes Next-generated E2E route types alongside normal types.
- `frontend/.gitignore`: ignores reports, test results, blob reports and Playwright cache.
- `frontend/vitest.config.ts`: caps costly jsdom/MSW fan-out at four workers after measured default-pool timeouts, with isolation/assertions/timeouts unchanged.
- `frontend/eslint.config.mjs`: excludes generated report scripts/artifacts from linting.
- `README.md` / `frontend/README.md`: runnable browser setup, terminal workflows,
  artifact/error policies, explicit frontend-only/MSW versus full-stack/MCP limits;
  frontend runbook retains read-only creation-dialog geometry and reproduction.
- `PLAN.md`: marks browser foundation delivered and production dialog fix deferred.
- `STRUCTURE.md`: this file inventory; existing application/backend inventory unchanged.

The published `backend/openapi.json` is unchanged. Browser navigation consumes the
existing typed client and MSW portfolio/account, holdings/analytics/ledger,
valuation/security and import-history/activity GETs; no API stubs, financial logic,
private fixtures, live smoke, production dialog changes or backend edits were added.
Generated worker, reports/recordings and `.next` output remain untracked. Local
`frontend/playwright/.cache/layout-investigation/create-*.png` and
`create-geometry.json` preserve read-only creation-dialog evidence for slice 2.
Final slice validation (commands run from `frontend/`):
- `npm install --save-dev --save-exact @playwright/test`: pinned 1.64.1; Chromium
  installed with `npx playwright install chromium`; documented `npm run test:e2e:install` also passed.
- `npm run test:e2e`: 6/6 passed (41.4s); `npm run test:e2e:headed -- --project=chromium`: 3/3 passed (22.2s).
- Two consecutive final plain `npm test` runs: 270/270, 34 files (42.87s and 44.59s).
- `npm run lint`, `npm run typecheck`, `npm run build`: exit 0. Normal build regenerated
  default Next ambient types; `next-env.d.ts` is unchanged in the delivered diff.
- Earlier launch/locator/lint failures were corrected with isolated output, semantic
  level-one title queries and a non-hook fixture callback name. Headed Chromium's
  exact missing-favicon 404 is trace-verified and recorded, not generically suppressed.
- Default-pool full unit runs had 269/270, 269/270 and 267/270 with five-second
  whole-test timeouts in existing dashboard/refetch workflows. Focused refetch tests
  passed 4/4; a four-worker experiment passed 270/270 before persisting the cap.
  No old test was edited/skipped, and no timeout, assertion or retry policy was relaxed.
- Installation reported 18 npm audit findings; dependency remediation was not attempted.
  No full-stack/live-account test, staging or commit was performed.
