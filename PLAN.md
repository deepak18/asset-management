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