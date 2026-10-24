# PLAN.md

## Core System Technology Stack
* **Frontend:** Next.js, React, TypeScript, Tailwind CSS, shadcn/ui
* **Backend:** Python FastAPI (Uvicorn / Gunicorn execution loop)
* **Database & Vector Layer:** PostgreSQL with `pgvector` extension
* **Data Access / ORM:** SQLAlchemy 2.0 (Async) + Alembic migrations
* **AI Orchestration Framework:** PydanticAI (for structured single-shot execution) + LangGraph (for complex state machines)
* **Local Inference Hub:** Ollama (Default Model: Qwen 2.5 / Llama 3.1)
* **Document Processing:** PyMuPDF, pdfplumber
* **Primary Integration Protocol:** Model Context Protocol (MCP) Clients
* **Dependency Manager:** `uv` (single tool for venv + locking + running)
* **Testing:** `pytest` + `pytest-asyncio` + `pytest-cov` (backend); frontend uses Vitest + React Testing Library. Tests are written **side-by-side** with code, never deferred (see `AGENTS.md` §11).

---

## Resolved Design Decisions (locked 2026-07-11)

These answers constrain the phases below. Treat them as authoritative.

1. **Single local user.** No multi-tenant accounts, no `user_id` foreign keys. Auth is a lightweight local gate only (optional `API_ACCESS_KEY`). Do not design multi-user data isolation.
2. **Free tools only.** No premium/paid API tiers are assumed. Because free providers (e.g., AlphaVantage free tier) are heavily rate-limited, a **local persistence/cache layer is mandatory** — fetched prices and fundamentals are stored in Postgres and re-served from there; the network is a last resort, not the hot path.
3. **Competitor groups start as a manually curated flat list** (config/DB seed of peer tickers per symbol). Automated peer resolution is a later, opt-in enhancement — never AI-guessed (would violate §1/§7).
4. **Returns are investor-centric, not security-centric.** We do **not** compute a stock's own market return. We compute **the user's realized/unrealized return on their own positions** from their ledger (cost basis, quantity, transaction dates, dividends, fees) — i.e., money-weighted return / XIRR on actual cash flows, plus simple unrealized P&L at current price. Portfolio-level XIRR aggregates all cash flows.
5. **Streaming = SSE for tokens, POST to ask.** The workspace panel submits each user question via a normal `POST` request whose response is an SSE stream (`text/event-stream`). SSE is server→client only; the *question* travels in the POST body, the *answer tokens* stream back on that same response. No WebSocket needed.
6. **Polymorphic, content-aware citation schema** (see below). Citations are persisted, never ephemeral MCP packet IDs.
7. **News via any free MCP server / RSS.** Pick a free, legally clean source; no paid news feeds.
8. **Multi-currency: USD first, INR next.** Build currency-aware from the start (store currency per transaction/holding, normalize to a portfolio base currency via an FX layer), even though only USD is enabled initially.

### Citation Schema (polymorphic by source type)

Every AI-surfaced figure must persist a typed citation. Minimum units:

* **Unstructured documents** (transcripts, PDFs, notes): `Document_UUID` + `Page_Number` + `Exact_String_Anchor` (5–10 word verbatim snippet for native frontend text-highlight; do **not** rely on brittle char offsets).
* **Regulatory filings** (10-K/10-Q): `Accession_Number` + `Item_Section` (e.g., "Item 7 MD&A") + `XBRL_Tag` (e.g., `us-gaap:GrossProfit`). Decoupled from table formatting.
* **Structured data streams** (AlphaVantage, local DB metrics): `Provider_Code` + `Data_Source_Table` + `As_Of_Timestamp` for full provenance and restatement auditing.

---

## Delivery Tracks & Parallelization (Frontend ∥ Backend)

Backend and frontend advance as **two parallel tracks joined by a single seam: the versioned REST API contract (OpenAPI).** Per `AGENTS.md` protocol #4 (context isolation), backend-core and frontend-UI work never share a chat turn — they run in **separate agent sessions**, each scoped to its own directory (`backend/` vs `frontend/`) with no shared code or DB (§9).

**The contract is the seam.** FastAPI auto-generates an OpenAPI schema from its typed route models. The frontend consumes that schema (generated TS types + a mock server), so UI work is **never blocked** on live endpoints — it builds against the contract, then swaps mocks for real calls at each sync point.

* **Track A — Backend (this lane):** Phase 1.1 API → 1.3 MCP market data → Phase 2 ingestion/RAG. Owns and publishes the OpenAPI contract.
* **Track B — Frontend (parallel agent lane), starts _now_, not at §1.4:**
  1. Scaffold Next.js (App Router) + TypeScript + Tailwind + shadcn/ui + Vitest/RTL.
  2. Build the design system, layout shell, and API client layer against **mocked** endpoints (e.g. MSW) derived from the OpenAPI contract.
  3. Implement §1.4 dashboard views (summary, allocation charts, ledger grid, watchlist) — mocks first, live endpoints as Track A ships them.
  4. Later: §2.4 research workstation, §3.x workspace side-panel (SSE token streaming).
* **Sync points:** whenever Track A updates the OpenAPI spec, Track B regenerates types and replaces the matching mock. The tracks integrate **only** through that document.

### Feature traceability — "AI earnings-call / news summary"
The requested capability (fetch transcripts/news for a holding → summarize sentiment, outlook, bull/bear, beat/miss, with citations) is **not a single phase.** It converges: MCP/RSS retrieval (§2.2 news, §1.3 + SEC filings) + RAG grounding (§2.1 `pgvector` embeddings) + structured, citation-anchored reasoning (§2.4 thesis canvas, §3.2 side-panel). It is deliberately sequenced late in Phase 2 because it depends on every prior seam.

---

## Testing Strategy (applies to every phase)

Testing is a **build-time discipline, not a phase.** Each task below is only complete when its tests land in the same change (`AGENTS.md` §11).

* **Framework:** `pytest` + `pytest-asyncio` (async routes/services) + `pytest-cov` for coverage. `backend/tests/` mirrors `backend/app/` one-to-one.
* **Pyramid:**
  * *Unit (majority):* pure functions and services with all provider boundaries mocked/faked. No network, no DB, no MCP.
  * *Integration (targeted):* real Postgres/pgvector via a disposable test DB and real MCP wiring, marked with `@pytest.mark.integration` and excluded from the fast default run.
  * *API (contract):* FastAPI routes via `httpx.ASGITransport`/`TestClient`, asserting status codes, response schemas, and citation payload shapes.
* **Determinism first:** All financial math (allocation, cost-basis P&L, realized/unrealized, XIRR, FX normalization) gets exhaustive edge-case coverage — empty ledgers, partial sells, splits, dividends, fees, mixed currencies, zero/negative cash flows. Known XIRR results are pinned against hand-computed fixtures.
* **AI paths:** Assert on structured output schemas, tool-routing, LangGraph state transitions, and citation presence/shape — never on exact LLM wording. LLM/MCP calls are stubbed in unit tests.
* **Fixtures:** Shared factories (portfolios, transactions, filings, documents) live in `backend/tests/conftest.py` and `backend/tests/factories/`.
* **Command:** `uv run pytest` (fast unit default) · `uv run pytest -m integration` (opt-in) · `uv run pytest --cov=app` (coverage).

### 1.1 Foundation & Service Orchestration
* Scaffold FastAPI project structure with strict asynchronous route handling.
* Establish PostgreSQL connection pooling with `pgvector` schema validation.
* Initialize Alembic data migrations pattern.
* Implement the core Docker Compose orchestration setup linking App, Database, and an MCP gateway client.
* Build a robust Ollama wrapper containing dynamic fallback configurations.

### 1.2 Portfolio Engine & Deterministic Calculators
* Construct database schemas for Portfolios, Holdings, Transactions (Buy, Sell, Split, Dividend), and Cash balances.
* Store a **currency** on every transaction/holding and a **base currency** per portfolio (USD initially; INR next). Route all cross-currency math through an FX normalization helper so enabling INR is config/data only.
* Write pure, tested Python calculation pipelines to compute:
  * Current asset allocation weights (grouped dynamically by Ticker, Sector, and Industry).
  * **Investor-centric performance** (not the security's own market return): unrealized P&L from cost basis vs. current price, realized P&L from sells, and **money-weighted return (XIRR)** computed from the user's actual dated cash flows (buys, sells, dividends, fees) at both the per-position and whole-portfolio level.
* **Tests:** Exhaustive `pytest` unit coverage for every calculator (allocation weights, cost-basis P&L, realized/unrealized, XIRR, FX normalization) against hand-computed fixtures, including empty ledgers, partial sells, splits, dividends, fees, and mixed-currency edge cases.

### 1.3 Baseline Market Data Ingestion (Via MCP)
* Implement an MCP client interface capable of connecting to the AlphaVantage MCP server (**free tier only**).
* Build extraction services to capture: live ticker prices, company profile descriptions, and normalized historical financial statements (Balance Sheets, Income Statements, Cash Flow statements).
* **Mandatory caching layer:** persist every fetched price/fundamental into Postgres with an `as_of` timestamp and serve reads from cache first. Respect free-tier rate limits with throttling + graceful "stale data" fallbacks so the app stays usable when quota is exhausted.
* **Tests:** Mock the AlphaVantage MCP client to verify cache-hit vs. cache-miss paths, TTL/stale fallback behavior, throttling, and correct `as_of` provenance stamping — no live network calls in unit tests.

### 1.4 Unified Portfolio Dashboard Interface
* Develop a performant Next.js user interface containing a clear Portfolio Summary overview.
* Render interactive asset allocation charts (Pie/Donut break-outs by sector and industry).
* Build an active transaction ledger grid alongside a custom market watchlist manager.

---

## Phase 2: Ingestion, Streaming News, & Competitor Benchmarking

### 2.1 Deep Document Processing Pipeline
* Build secure local document uploading endpoints supporting PDF, TXT, and Markdown files.
* Execute clean extraction layers targeting Key Financial Tables, Management Discussion & Analysis (MD&A), corporate guidance outlooks, and identified risk declarations.
* Store raw source documentation locally, write clean text extractions to Postgres, generate embeddings via local Ollama models, and catalog them within `pgvector`.
* **Tests:** Unit-test the parsing/extraction layer against small fixture PDFs/TXT/MD files (assert page numbers and exact-string anchors for citations); mock the embedding model so ingestion logic is verified without invoking Ollama.

### 2.2 Streaming News & Macro Engine
* Implement a structured data collection service using open-source RSS or **any free News/Macro MCP server** (no paid feeds). Pick a legally clean source.
* Build a streaming background ingestion loop that links news items semantically to tickers present inside user portfolios or watchlists.

### 2.3 Connected Competitor Matrix Engine
* **Start with a manually curated flat list** of peer tickers per symbol (config/DB seed). Automated peer-group resolution is a later, opt-in enhancement — peers are never AI-guessed.
* Develop an automated parallel processing engine to fetch fundamental metrics across a target stock and its defined competitors simultaneously (respecting the free-tier cache layer from §1.3).
* Leverage local AI models using Pydantic structural parsing to extract side-by-side comparative matrices (e.g., contrasting gross margins, leverage ratios, and capital allocation efficiency trends against peers).
* **Tests:** Verify the parallel fetch orchestration and matrix assembly with mocked providers; assert the structured comparison schema is well-formed and every metric carries a valid typed citation (never assert on LLM wording).

### 2.4 Interactive Research Workspace View
* Build a target workstation view focused on a specific chosen Ticker symbol.
* Construct an integrated AI summary canvas that runs structured analysis to produce: A core investment thesis framework, isolated Bull vs. Bear cases, relative valuation arguments, and open research questions.
* Ensure all AI-generated assertions contain strict source-anchored visual citations.

---

## Phase 3: Contextual Workspace Side-Panel & Interactive Inspector

### 3.1 Context-Aware Sidebar Integration
* Replace the design pattern of a generic conversational chatbot window with an Interactive Workspace Side-Panel seamlessly mounted across the Portfolio and Research views.
* Inject state telemetry automatically into the panel context (e.g., passing active screen data such as the current portfolio view, selected stock ticker, or actively opened financial document text).

### 3.2 Multi-Context Vector Tool Synthesis
* Build query execution paths inside PydanticAI allowing the side-panel helper to intelligently call tools querying across diverse information vectors: Portfolio records, Live MCP data streams, Local Document stores, and Historical research notes.
* Enforce streaming REST API architectures to deliver sub-second, real-time token rendering directly to the UI panel. **Transport:** the panel sends each question via `POST /workspace/ask` (question in the request body); the server responds with an SSE `text/event-stream` that streams answer tokens back on that same response. SSE is server→client only, so all user input rides the POST — no WebSocket required.
* **Tests:** Assert tool-routing selects the right vectors (portfolio / MCP / documents / notes) for representative questions, and API-test the `POST /workspace/ask` SSE endpoint (correct `text/event-stream` content type, event framing, and terminal event) using a stubbed LLM stream.

### 3.3 Active On-Screen Prompt Action System
* Implement contextual click actions across the research dashboard (e.g., selecting an erratic financial line item or a piece of text within an earnings transcript instantly passes that segment into the Side-Panel with specific predefined intents: *"Audit this metric against SEC data"* or *"Compare this statement with top peer guidance"*).

## Delivered Dashboard Capabilities

- [x] Holding-history review, missing-transaction repair and fingerprint-bound confirmation, with read-only ledger provenance.
- [x] Portfolio-scoped sector/industry suggestions with accessible editing and explicit saves.
- [x] Interactive allocation donuts with linked slice/legend previews, pinning and current-holding breakdowns using backend weights.
- [x] Persistent bookmarkable Overview, Reported Holdings, Ledger Analytics, Imports and Account Settings pages; brokerage-selected Robinhood/Vanguard forms live only on Imports, and Taxable Brokerage maps to the existing TAXABLE account type.

## Account & Exposure Intelligence — Approved Delivery Plan

This is the next product priority, before broad Phase 2 news/RAG work. The goal is
trustworthy personal-account accounting and household economic exposure, followed by
fund-manager decision tools and an equity-research workstation. Implementation status
must be checked against Git and OpenAPI, not inferred from this document alone.

### Fresh-chat entry point

1. Read `AGENTS.md`, `STRUCTURE.md`, this section, and the applicable agent profile.
2. Check `git status --short` and recent commits before editing. Do not overwrite
   unrelated work. Backend/UI implementation uses separate delegated agent contexts.
3. Read `backend/app/portfolio/accounts.py`, `providers/account_provider.py`, the
   portfolio schemas/models, import modules, and actual `backend/openapi.json`.
4. Implement one test-green slice, update docs and OpenAPI/types, commit explicit
   paths with a one-line Conventional Commit, then proceed to its dependent slice.
5. No calculations in LLMs, no direct service I/O, no invented fund identities or
   market data, no null-to-zero coercion. Keep raw personal exports outside Git.

### Dependency-ordered feature slices

| # | Scope / layer | Depends on | Acceptance tests | Intended commit |
|---|---|---|---|---|
| 1 | Shared security identity, account metadata, valuation-only snapshots; migrations → pure policy → providers → API | Existing portfolio engine | Additive migration/drift, old portfolio compatibility, exact decimals, nullable basis, dates, alias conflicts, atomic rollback, no ledger side effects | `feat(portfolio): add account and valuation foundations` |
| 2a | Vanguard two-section CSV; pure parse/preview → atomic persistence → API/OpenAPI | 1 | Both sections, incomplete/full activity, date/identifier validation, repeated and overlapping imports, reinvestment semantics, reconciliation, conflicts, rollback | `feat(imports): import vanguard retirement statements` |
| 2b | Account metadata, preview/confirm upload, reported balances/activity/reconciliation; typed client/hooks → UI | 2a published contract | MSW/RTL success/failure/cancellation, decimal/null fidelity, portfolio switching, refresh, repeated upload, leading zeros, unknown fund symbols | `feat(frontend): add retirement account import workflow` |
| 3 | Selected-account meta-portfolio with direct-instrument aggregation | 1–2 | Deduplicate account selection, canonical security identity, FX availability, incomplete denominators, zero/empty accounts, account drill-down | `feat(portfolio): aggregate selected account exposure` |
| 4 | Free-source capability spike; dated fund constituent snapshots behind a provider | Verified fund identities | Actual tool discovery, free entitlement, source dates, full-vs-partial weights, missing data, stale cache, licence/transport checks | `feat(marketdata): add dated fund holdings provider` |
| 5 | Fund look-through and direct-plus-indirect company exposure; API then UI | 3–4 | Value conservation, unexplained residuals, company/share-class mappings, fund-of-fund recursion/cycles, no double counting | `feat(portfolio): add fund look-through exposure` |
| 6 | Concentration, fund overlap, targets/drift, contribution scenarios and fund fees | 5 | Source-weight denominators, partial expense-ratio coverage, deterministic scenario totals and constraints | `feat(portfolio): add allocation decision tools` |
| 7 | Account cash-flow ledger, valuation history and meaningful performance | Account event design | External vs internal flows, reinvestments, fee/dividend treatment, transfer cancellation at aggregate scope, benchmark total-return consistency | `feat(performance): add account cash flows and history` |
| 8 | Fundamentals, peer comparison, valuations, thesis and decision journal | Existing statements + persisted citations | Period/unit/currency consistency, deterministic ratios/valuation sensitivity, source-linked facts and thesis revisions | `feat(research): add fundamental analysis workspace` |
| 9 | Targeted review queue, filings/earnings monitoring, then grounded AI | 6–8, document/citation foundations | Relevant owned-company events, deduplication, review triggers, citation enforcement and structured AI scaffolding | `feat(research): add evidence-based monitoring` |

First release boundary: slices 1–5. Current requested implementation: 1, 2a and 2b.
No slice is delivered merely because its proposed commit message appears here.

Delivery status:
- [x] Slice 1 backend foundation: account metadata, shared identities and reported valuations; 491 backend and 204 frontend regressions passed.
- [x] Slice 2a delivered backend import core: Vanguard preview, atomic import, activity and reconciliation; validated with 580 tests, Ruff and mypy. UNKNOWN stable securities and explicit mapping before import are approved scope.
- [x] Slice 2b delivered typed frontend account/import/reported-holdings workflow; final 246 frontend tests in 33 files, lint and typecheck passed.
- [ ] Slices 3–9: not implemented.

### Slice 2a backend implementation status

- Implemented a separate synchronous retirement API/OpenAPI: multipart preview
  (200), explicitly confirmed commit (201), retained import history/detail and all
  source activity (200); scoped 404, conflict 409, upload-limit 413, invalid-input 422.
- Pure parsing preserves both source sections, exact decimal facts, raw identifiers,
  line/checksum provenance and same-file event multiplicity. Supported codes are
  contribution 114001 and dividend reinvestment 219004; other codes are visible
  typed blocking issues, not claimed full historical support. Unsupported movement
  stays null. Partial history, negative implied openings and complete-history
  mismatches are explicit; share reconciliation never enables performance.
- Preview writes nothing. Tokens bind bytes/options and relevant account, alias,
  import/activity and valuation state. Atomic provider commit binds unassigned
  accounts, creates only UNKNOWN/null-ticker identities, stores the whole snapshot,
  all activity and diagnostics together. Raw-file storage is behind StatementStorage;
  a failed DB commit may leave only an unreachable checksum blob, never partial rows.
- Revision 0010 adds retirement ownership/activity tables. Legacy Robinhood and
  ticker ledger/calculators are unchanged. Different-file overlap is conservatively
  rejected for any shared canonical fingerprint; combine nonoverlapping periods.
  Same-date conflicts retain strict foundation provenance/content semantics.
- **Required future work before slice 4 (not a slice 2a blocker):** existing
  securities POST creates immutable identities and rejects an existing alias (409).
  Explicit mappings before import and stable UNKNOWN/null-ticker securities are
  approved slice 2a scope. Post-import security metadata amendment, ticker identity
  confirmation/update and alias remapping require a separately approved schema/API
  slice before fund-source integration and look-through. Do not guess public fund
  identities or add a speculative mapping endpoint to this delivered import core.
  Slice 2b frontend is delivered below; slices 3–9 are not implemented.
- Offline validation from backend: `uv run pytest` **580 passed, 3 deselected**;
  `uv run ruff check .` passed; `uv run mypy` passed (57 source files). Migration
  upgrade/downgrade/drift, mocked storage/provider boundaries, injected rollback,
  stale reviews, overlap, closed-fund retention and API/OpenAPI parity are covered.
  Only fictitious fixtures and disposable SQLite databases were used. No external
  calls, live DB, frontend edits, staging or commits. Root/backend runbooks contain
  the 0010 prerequisite, Swagger workflow, exact schemas/nullability and limitations.

### Slice 1: identity, account and valuation contracts

- A portfolio remains the account boundary; add optional custodian, string
  `external_account_id` and account type: UNKNOWN, TAXABLE, TRADITIONAL_401K,
  ROTH_401K, TRADITIONAL_IRA, ROTH_IRA, OTHER. Preserve leading zeros.
- Shared numeric security IDs are independent of ticker. Instrument types include
  UNKNOWN, STOCK, ETF, MUTUAL_FUND, COLLECTIVE_TRUST, TARGET_DATE_FUND, CASH, OTHER.
  Source-scoped aliases distinguish plan investments/share classes. Existing ticker
  ledgers remain backward compatible; migrating their identities is separate work.
- Never map abbreviated plan fund names to a public ticker without confirmation.
  A target-date name does not prove a listed share class or product structure.
- Reported valuation snapshots are independent, dated observations, NOT opening
  BUYs. Require an explicit valuation date and currency. Cost basis is nullable;
  present value does not imply historical acquisition cost or performance.
- Use reported values as authoritative observations; do not overwrite them with
  quantity × rounded displayed price. Preserve all three original decimal fields.
- Store snapshot history atomically. Exact same-date content is idempotent;
  conflicting same-date content is 409, not an implicit destructive replacement.
  Latest is by valuation date, not upload order. Incomplete snapshots are explicit.
- Mixed-currency snapshots are refused until supported FX is available. Returned
  money/quantity values are decimal strings. Unknown P&L and returns remain null.
- API: existing portfolio POST/GET gain backward-compatible metadata;
  PATCH `/api/v1/portfolios/{id}/account` (200/404/422);
  POST/GET `/api/v1/securities` (201/200, 409 conflict, 422 validation);
  POST/GET `/api/v1/portfolios/{id}/valuations` (201/200, 404/409/422).
  GET returns a REPORTED_SNAPSHOT envelope with AVAILABLE/PARTIAL/EMPTY and
  nullable snapshot. This is a separate view, never added to legacy analytics.
- Additive migration `0009_account_valuations`; explicit Alembic upgrade required.

### Slice 2: Vanguard CSV requirements and financial policy

The user supplied a private Vanguard CSV with two headers separated by blank lines:

- Holdings: `Plan Number,Plan Name,Fund Name,Shares,Price,Total Value,`
- Activity: `Account Number,Trade Date,Run Date,Transaction Activity,Transaction Description,Investment Name,Share Price,Transaction Shares,Dollar Amount,`

Do not commit that private sample or real plan/account metadata. Use fully fictitious
fixtures with the same structure. Support trailing empty columns, blank lines,
UTF-8 BOM, CSV quoting and decimal/date validation. Preserve source line references.
The first section is current holdings, not the opening balance before activity.
The export has no holdings date, currency, cost basis, public tickers or unique
transaction IDs. UI/API must request a real holdings `as_of` date and currency;
never use the latest trade/run date or upload clock as a fabricated valuation date.

1. **Preview before commit:** return reported holdings/total, source account/plan,
   activity, mapped/unmapped securities, warnings and typed reconciliation. Preview
   is read-only. Unsupported activity remains visible, not silently skipped.
2. **Account scope:** one source account per import in the first iteration. Plan
   number and activity account may differ only in leading-zero formatting; compare
   normalized identifiers but preserve the raw strings. Refuse genuine mismatch or
   inconsistent fund/security mappings. Do not guess traditional vs Roth or employer
   vs employee contributions from generic descriptions.
3. **Activity facts:** `114001` / Plan Contribution has acquired units and a reported
   dollar amount, but must not become both a fictitious opening BUY and another
   purchase on top of current balances. `219004` / Dividends on Equity Investments
   with acquired shares represents reinvestment information; preserve the cash
   distribution and acquired units without double-counting external contributions.
   Trade date and run date are separate facts; source amount is authoritative when
   share price × rounded units differs. Unknown codes need review.
4. **Separate activity:** retain observed account activity with source ownership,
   code, dates, quantities and amounts. Do not feed a partial-period history into
   legacy FIFO/XIRR or claim a trustworthy opening lot. Support future explicit
   external-flow and reinvestment event modeling without manufacturing history.
5. **Reconciliation:** current holdings are the balance observation; activity is
   explanatory history, not extra holdings. Show observed movement, closing units,
   prior units implied by the supplied period and mismatches/unsupported events.
   Implied prior units are diagnostics, never fabricated acquisitions/cost basis.
   Complete-history assertions require validation; a one-month export is not
   proof of inception history. Negative inferred balances are blockers.
6. **Idempotency:** checksum blocks identical uploads; source-event fingerprints
   detect overlap across different exports. Source activity code is NOT a unique
   event ID. Preserve identical-row multiplicity or refuse ambiguous overlap for
   review; do not collapse legitimate equal contributions. Commit securities,
   snapshot, activity and import metadata atomically. A failed transaction leaves
   no partial positions/security aliases; retries must not inflate holdings.
7. **Safety:** date/account/currency validation and upload limits; explicit 404,
   409 conflicts and 422 invalid input. Do not repurpose the Robinhood import flow
   until schemas, recovery, frontend and regressions are covered. A separate typed
   retirement import API is acceptable; published OpenAPI is the final contract.
8. **UI workflow:** create/select retirement portfolio → enter account metadata →
   choose Vanguard CSV/date/currency → inspect preview and warnings → confirm →
   inspect reported holdings and activity. Unknown basis/returns render as dashes,
   security names remain usable without tickers, and repeat uploads explain conflicts.
   Preserve drafts/errors; discard stale portfolio/upload responses after switching.

### Meta-portfolio and look-through invariant contract (slices 3–5)

- Select accounts explicitly; never count an account twice. Report owned instruments
  separately from underlying economic exposures; constituents never become tax lots.
- Company exposure = direct market value + sum(fund market value × constituent weight).
  Weights divide by the selected accounts' supported total value; expose missing
  account valuations/FX and never call a priced subset the complete household total.
- Fund weights require as-of dates, source URLs/filing identifiers, retrieval time,
  coverage and FULL/PARTIAL/UNAVAILABLE/STALE distinctions. Never normalize a top-ten
  holdings list to 100%. Keep unmapped/unexplained weight and cash/non-equity exposure.
- Fund-of-funds traversal needs deterministic cycle/depth guards and retained paths
  explaining which account/fund created exposure. Company aggregation and share-class
  mappings must be sourced or manually confirmed, never LLM-guessed.
- Cache dated snapshots persistently; do not replace holdings history with one mutable
  cache entry. Surface mismatched source dates rather than implying simultaneous data.

### Subsequent priorities and changes to the original roadmap

- Data trust precedes new metrics: import/ledger reconciliation, overlapping-export
  safety, a data-health panel, and backup/export plus a tested restore runbook.
- Concentration limits, asset-class/geographic/currency exposure, fund overlap,
  allocation drift and contribution-led rebalancing precede elaborate VaR/factors.
- Performance must distinguish external contributions/withdrawals from trades;
  inter-account transfers cancel for the selected aggregate. Audit portfolio XIRR
  history gates: holding-level safeguards are not currently applied equivalently
  by `PortfolioService`. Do not advertise existing trade-flow XIRR as account return.
- Adding time-weighted return and benchmark comparisons deliberately extends resolved
  decision #4; existing investor-centric XIRR remains available under honest labels.
- Ratios, peer matrices and valuations are deterministic. Phase 2.3's AI wording means
  explain/extract from unstructured cited documents, NOT calculate a peer matrix from
  already structured financial statements. Prefer a thin source-linked research
  workflow before a broad generic RAG/news/chat subsystem.

### Free MCP research — documentation inspected in this delivery

Research scope: public GitHub repository READMEs and official documentation retrieved
read-only during this delivery (user session date 2026-10-23). These are documentation
findings, NOT live tool/entitlement tests. No account data was sent externally and no
third-party MCP code was installed or executed. Sources can change; pin/recheck at
integration time. Open-source server licence does not grant rights to upstream data.

| Candidate / evidence | Useful coverage | Free/access and integration limits |
|---|---|---|
| [Official AlphaVantage MCP](https://github.com/alphavantage/alpha_vantage_mcp), [hosted docs](https://mcp.alphavantage.co/), [ETF API docs](https://www.alphavantage.co/documentation/#etf-profile) | Existing quotes/profiles/statements; REST ETF_PROFILE documents holdings and asset/sector allocation | Free API-key signup advertised; endpoint quotas/entitlements still need testing. Hosted MCP tool catalogue did not list ETF_PROFILE in retrieved docs although REST does. Do not promise free MCP constituent access until tools/list + a real free-key request succeeds. Docs now recommend OAuth; existing API-key-in-URL transport is marked deprecated. Never log keys. |
| [narumiruna/yfinance-mcp](https://github.com/narumiruna/yfinance-mcp), [yfinance fund data](https://ranaroussi.github.io/yfinance/reference/api/yfinance.domain.funds.FundsData.html) | `yfinance_get_fund_data`: ETF/mutual-fund top holdings, asset classes, sectors and operations; price/news/fundamental tools | MIT server using yfinance; no paid upstream subscription assumed, but Yahoo access/terms/rate limits apply. `max_rows=0` removes tool truncation, NOT upstream top-holdings incompleteness. Treat as PARTIAL until coverage verified. Transport needs pin/source inspection before integrating with existing HTTP-only client. |
| [EdgarTools upstream](https://github.com/dgunning/edgartools), [MCP setup](https://edgartools.readthedocs.io/en/latest/ai/mcp-setup/), [N-PORT guide](https://edgartools.readthedocs.io/en/latest/guides/nport-data-object-guide/) | Company filings/XBRL; library explicitly supports fund portfolios from N-PORT | Self-hosted MIT library/server; no API key, identified SEC user agent required and fair-access limits apply. Docs support stdio and streamable HTTP. Distinguish free self-hosting from hosted edgar.tools paid/full-result service. N-PORT library capability does NOT prove a particular MCP tool exposes complete portfolios; verify tool schemas or add a narrow local wrapper. Filing-based data is delayed, not live ETF holdings; match fund series/share class and filing dates. |
| [stefanoamorelli/sec-edgar-mcp](https://github.com/stefanoamorelli/sec-edgar-mcp) | Company facts, filings and source SEC URLs | Self-hosted AGPL-3.0; identified SEC user agent, stdio/streamable HTTP advertised. No authentication built in; bind privately. Not established as a complete fund holdings source. Review licence before redistribution/modification. |
| [stefanoamorelli/fred-mcp-server](https://github.com/stefanoamorelli/fred-mcp-server) | `fred_browse`, `fred_search`, `fred_get_series` for macro series | Self-hosted AGPL-3.0; FRED API key required; stdio or HTTP. Free-access candidate, not live validated. FRED official key-doc request timed out during research, so upstream key terms were not independently revalidated. Not a constituent provider. |
| [Alex2Yang97/yahoo-finance-mcp](https://github.com/Alex2Yang97/yahoo-finance-mcp) | Prices, statements, corporate actions and news | MIT; README showed local process configuration. `get_holder_info` describes OWNERS of a security, not investments inside a fund; do not confuse institutional ownership with fund constituents. Secondary candidate, not the primary look-through source. |

**Recommended source strategy (updated 2026-10-24):** prioritize the self-hosted
EdgarTools stock/ETF capability spike described below, retaining AlphaVantage for
quotes. Evaluate EdgarTools N-PORT plus issuer holdings files behind the same typed
provider; verify AlphaVantage ETF free entitlement/MCP as a complementary source. Use yfinance MCP as explicitly
partial composition/metadata fallback, and retain manual issuer-file upload. Add FRED
only when macro workflows need it. No researched source establishes full coverage of
all plan-specific investments. Do not substitute ETFs for unresolved mutual funds/CITs.

**Integration gate:** pin version/commit and review licence/dependencies; discover tool
schemas over the configured transport; test known public examples (not personal account
files); assert units, sum/denominator, source date, full-vs-partial coverage and stale/error
behavior; then add mocked provider tests and opt-in live smoke tests. Keep network I/O
behind providers and citations durable. No MCP installation is needed for slices 1–2.

### Slice 2b frontend implementation status

- Delivered account metadata Save/Cancel with actual selected-portfolio reads,
  leading-zero string IDs, nullable clearing and preserved error/unsaved drafts.
- Separate Vanguard upload requires a user-supplied holdings date and USD, offers
  conservative inception-history opt-in, displays all source holdings/mappings and
  inspectable activity/lines, issues and backend reconciliation, then requires
  explicit acknowledgement plus can_commit before exact multipart confirmation.
- Reported Holdings is primary for available/partial snapshots and retirement types;
  names join by numeric security identity, tickers are not guessed, unknown values
  stay unavailable and no legacy zero balance is substituted. Ledger Analytics
  remains an explicitly separate brokerage view, never summed with snapshots.
- Scope/generation guards abort/ignore stale reads/writes and prevent double submit.
  Changed file/options/account/resources invalidate review. Duplicate/overlap/stale
  409 guidance requires a new preview and preserves upload drafts. Success refreshes
  snapshot, security names, account/selector metadata, retained history and activity.
- Published OpenAPI types regenerated; request aliases preserve omission semantics
  for defaulted account_type without weakening read types. No backend contract,
  executable, financial math, dependency or MCP changes. Fictitious-only MSW state
  persists a fixed demo upload; arbitrary CSV parsing requires the live backend.
- Validation: npm run typegen succeeded; final npm test passed 246 tests in 33 files;
  npm run lint and npm run typecheck exited 0. Independent backend validation passed
  580 tests (3 live integrations deselected), Ruff and mypy (57 source files).
  Same-account refresh preserves ledger controls; dialog focus restoration runs
  before DOM removal. Regression coverage retains the original focus assertions.
  The broad button-label scenario was split into bounded independent tests with
  every assertion and timeout retained after an observed five-second timeout.
- The private attached sample passed a local read-only parse/preview: 12 holdings,
  24 activities (22 contributions and 2 reinvestments). No private bytes entered
  tracked fixtures or the live database. An explicitly assumed diagnostic date was
  used only in memory; users must still supply the actual holdings valuation date.
- Live browser/API integration and external MCP tool calls were not exercised.
  Post-import identity amendment remains the separate future backend seam already
  identified by slice 2a.

### EdgarTools stock and ETF integration plan (2026-10-24)

Planning only: no dependency, server, configuration or live tool validation is delivered.
This prioritizes self-hosted EdgarTools as the next SEC-data capability spike;
AlphaVantage remains the existing quote provider, not a dependency to replace first.
Existing research links above are background evidence, not newly verified tool support.

- [x] Record the stock/ETF integration scope and acceptance gates.
- [ ] Pin and review the self-hosted EdgarTools release, licence and dependencies; configure an identified SEC user agent, fair-access throttling, timeouts and private HTTP binding. Discover actual MCP tools and schemas over streamable HTTP supported by the current client; do not assume stdio support in that client.
- [ ] Stocks: expose typed filing discovery and period/unit/currency-aware XBRL facts behind SECProvider and, where normalized fundamentals are needed, MarketDataProvider. Retain CIK, accession, source URL, reporting period and retrieval time. Ratios stay deterministic, outside AI.
- [ ] ETFs/funds: verify whether discovered tools expose N-PORT holdings. If not, design a narrow local MCP wrapper around the pinned library, behind a typed fund-holdings provider. Confirm fund series/share-class identity first; the separate post-import security amendment seam is a prerequisite for unresolved imported funds.
- [ ] Persist dated constituent snapshots with exact decimal quantities/weights, source denominator, filing/report dates, accession, source URL and retrieval time. Distinguish FULL/PARTIAL/UNAVAILABLE/STALE, retain residuals, and never normalize a top-holdings subset to 100%. Filing-based holdings are delayed, not live ETF composition or quotes. Unsupported ETFs, CITs and plan products stay unavailable, never substituted.
- [ ] Deliver schemas/migrations, pure normalization, provider/cache/service and mocked tests, then API/OpenAPI, then a separate typed frontend slice. No business logic or direct SEC I/O in AI/routes/browser components; no speculative endpoint is published by this plan.
- [ ] Acceptance: mocked tool discovery/malformed results/timeouts/limits; cache hit/expiry/stale fallback; restated facts and units/periods; identity mismatch; partial weights/residuals; durable citations and null fidelity. Add opt-in live smoke tests using public stock and ETF examples only, plus route/MSW tests after the seam is published.

This spike informs roadmap slices 4 (dated fund holdings) and 8 (fundamentals);
it does not mark either implemented or claim complete ETF coverage. Reuse the
existing quote provider and issuer-file/explicit-partial fallback strategy rather
than treating SEC filings as a universal market-data replacement.

## Frontend browser testing and dialog follow-up

- [x] Slice 1: pinned Playwright Chromium foundation with desktop/narrow real-browser
  route navigation, active-page semantics, persisted portfolio/query selection,
  Robinhood/Vanguard form selection and no imports on Overview. Uses the existing
  fictitious MSW contract responses, not full-stack/live accounts. Own loopback
  server on 3100, forced mock/same-origin API config, automatic public worker,
  isolated Next E2E output/lock, browser error checks and failure artifacts/HTML report.
  Headless, headed, UI, debug, report and Chromium-install terminal commands are
  documented. IDE Playwright MCP registration is separate and not configured.
- [x] Slice 2: repair New Portfolio's filtered-header containing block with a
  hydration-safe body portal, viewport-bounded internal scrolling, full-control
  keyboard boundary, layout-phase trigger restoration and nested-safe body lock.
  Chromium regressions assert overlay/panel/control geometry and hit-testing at
  desktop, narrow, short and landscape sizes; long history scrolling, cancellation,
  focus, mock POST 201/list refresh and one-write auto-selection are covered.
  Successful tests attach screenshots/geometry; locally preserved tests-before-fix
  evidence proves the old overlay-height failure. Original navigation/form and focus
  regressions stay active. No backend/OpenAPI, typegen or financial policy changes;
  browser evidence remains frontend/MSW-only, not live/full-stack or MCP validation.

Slice 1 validation: Chromium desktop/narrow **6/6 passed**; existing Vitest suite
**270/270 passed in 34 files**. Published `backend/openapi.json` is unchanged;
no backend changes, generated API changes, live smoke or financial calculations.
Unit-runner tooling caps expensive jsdom/MSW fan-out at four workers after repeated
parallel whole-test timeouts; existing assertions, isolation, timeouts and retries
are unchanged. The frontend runbook records the experiment and the separate
creation-dialog containing-block bug reproduced read-only for slice 2.

Slice 2 final validation: `npm test` 275/275 (34 files); `npm run test:e2e`
24/24 including unchanged navigation/form cases; targeted headed dialog suite 9/9.
Lint, typecheck and normal production build exited 0. Generated next-env.d.ts is
restored, with no delivered diff. The frontend runbook records tests-before-fix,
intermediate autofocus/test-authoring failures and ignored before/after PNG/JSON
evidence. No live/full-stack/MCP coverage, staging or commit is claimed.
