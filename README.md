# asset-management

Local AI-powered **Investment Research Platform** — an analytical terminal (think Bloomberg / Koyfin / NotebookLM), **not** a chatbot. Runs locally on Ollama, with the frontend, backend API, and MCP servers deployable independently.

> 📐 **Architecture rules:** see [`AGENTS.md`](./AGENTS.md) \
> 🗺️ **Build roadmap:** see [`PLAN.md`](./PLAN.md) \
> 🧭 **Directory source of truth:** see [`STRUCTURE.md`](./STRUCTURE.md) — read before writing code.

---

## Tech Stack
- **Frontend:** Next.js 16 · React 19 · TypeScript (strict) · Tailwind · shadcn/ui-style primitives · Vitest/RTL *(dashboard scaffolded, mocks-first)*
- **Backend:** Python 3.12+ · FastAPI · SQLAlchemy 2.0 (async) · Alembic
- **DB / Vectors:** PostgreSQL 16 + `pgvector` (via Docker)
- **AI:** PydanticAI (single-shot) + LangGraph (state machines); Ollama default, cloud via config *(in progress)*
- **Integration:** Model Context Protocol (MCP) clients *(planned)*
- **Tooling:** [`uv`](https://docs.astral.sh/uv/) (env + lock + run) · `ruff` · `mypy` · `pytest`

## Layout (high level)
```
backend/   FastAPI service — domain modules behind provider interfaces
frontend/  Next.js app — talks to backend via REST only           (dashboard, mocks-first)
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
| REST API (`/health`, portfolio summary/transactions/holdings/analytics incl. unrealized P&L + allocation) | ✅ |
| PostgreSQL + pgvector via Docker Compose | ✅ |
| Ollama AI-client wrapper (typed `LLMClient`, config-only provider swap) | ✅ interface + Ollama adapter, HTTP boundary unit-tested |
| Market data via AlphaVantage MCP (read-through Postgres cache, throttle, stale fallback) | ✅ provider + cache wired; MCP boundary unit-tested (live path opt-in) |
| Documents/RAG, research, workspace panel | ⬜ planned |
| Frontend dashboard (summary, allocation donuts, ledger, watchlist) | ✅ scaffolded, mocks-first (Vitest/RTL green); swaps to live API per contract |

The generated API contract lives at [`backend/openapi.json`](./backend/openapi.json) (the seam the frontend generates types from).

---

## Prerequisites
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — manages the Python version, virtualenv, lockfile, and command running.
- **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** — runs PostgreSQL + pgvector. (uv installs Python 3.12+ itself, so a system Python is not required.)
- **[Node.js ≥ 20](https://nodejs.org/)** + npm — only needed for the `frontend/` app (`winget install OpenJS.NodeJS.LTS` on Windows).

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

Existing installations, including those already on `0006` or `0007`, must upgrade
to `0010` before starting this backend. Revision `0006` records snapshot/observed
origins for holding XIRR; `0007` adds transaction-deletion audit tombstones; `0008`
adds nullable holding-scoped history confirmation metadata; `0009` adds account
metadata and separate reported valuation tables; `0010` adds retirement imports and
observed account activity. Existing ledger facts
are not rewritten or automatically confirmed. Ambiguous legacy unowned transactions
remain unknown rather than being relabeled as observed purchases.
No application-database migration is run automatically by the API.

**5. Run the API.**
```powershell
uv run python -m uvicorn app.main:app --reload
```
Open **http://localhost:8000/docs** for interactive Swagger UI. `GET /health` works immediately; the portfolio routes serve data once a portfolio is seeded.

**Stop the stack:** `docker compose down` (keeps data) · `docker compose down -v` (wipes the data volume for a fresh DB).

---

## Frontend (dashboard, mocks-first)

The UI builds and tests with **zero live backend** — it runs against MSW mocks
shaped by the OpenAPI contract, then swaps to the real API by config. See
[`frontend/README.md`](./frontend/README.md) for the full runbook.

```powershell
cd frontend
npm install
cp .env.local.example .env.local     # NEXT_PUBLIC_API_MOCKING=enabled runs mock-only
npm run dev                          # http://localhost:3000
```

Point it at the live API by setting `NEXT_PUBLIC_API_BASE_URL` (default
`http://localhost:8000`) and leaving `NEXT_PUBLIC_API_MOCKING` unset. When the
backend republishes `openapi.json`, run `npm run typegen` to regenerate types.

### Run the full stack locally (live mode)

Two terminals — backend on `:8000`, frontend on `:3000`:

```powershell
# terminal 1 — API (see backend/README.md; SQLite fallback needs no Docker)
cd backend
uv run python -m uvicorn app.main:app --reload      # http://localhost:8000/docs

# terminal 2 — UI in live mode (no mocking flag = calls the real API)
cd frontend
npm run dev                               # http://localhost:3000
```

Both browser-facing prerequisites are now satisfied by the backend lane, so
live mode works out of the box:

1. **CORS** — the backend enables config-driven CORS for the dev origin
   `http://localhost:3000`, so the dashboard's cross-origin `GET`s go through.
2. **Data entry** — a fresh database is empty, not automatically seeded. Create a
   portfolio through the UI or `POST /api/v1/portfolios`, then add snapshots,
   transactions, or import a statement. The portfolio picker reads the API list.

### Holding classification and import repair (backend)

- Holdings and analytics positions expose `classification_source`
  (`MANUAL | PROVIDER | NONE`) and enum `data_gaps` for user-correctable facts.
  Missing prices are reported separately in `unpriced_tickers`.
- `GET /api/v1/portfolios/{id}/holdings/{ticker}` returns a single holding or `404`.
  `PATCH` preserves omitted fields, clears explicit nulls, and always sets `MANUAL`.
  Successful edits are visible in the next analytics GET; allocations are computed
  on read when prices are available.
- `POST .../holdings/classify` protects `MANUAL` by default; `?refresh=true` opts
  into replacement. Follow `next_cursor` as `after_ticker` until `remaining=0`.
  Unresolved lookups advance the cursor and are retried on a new sweep. Repeated
  fresh sweeps are safe but need not decrease `remaining`.
- Classification `503` means configure the market-data URL/key. Quota exhaustion
  or an upstream outage instead returns `200` with per-ticker
  `PROVIDER_UNAVAILABLE`; wait and retry rather than asking for a new key.
- Import jobs expose structured `unresolved_items`; list them at
  `GET .../unresolved` and submit a source-matching correction at
  `POST .../unresolved/{item_id}/resolve`. Resolution is atomic and rejects repeats.
  Optional `?history_complete=true` enables conservative split inference only for
  user-confirmed complete opening history.
- On startup, interrupted imports become `FAILED`. `POST .../imports/{job_id}/retry`
  verifies retained bytes and replaces only that job's owned partial transactions.
  Legacy imports without ownership tags are refused rather than risking data loss.
  Use **one API process**: this recovery policy is not multi-worker coordination.

See [`backend/README.md`](./backend/README.md#4-sector--industry-classification)
for the full contract, edge cases, and repair workflow.

### Allocation donut interactions

Hover a sector/industry slice or its legend row to highlight both and inspect the
category, market value and allocation percentage in the detail card below. Click
or tap a slice or legend row to pin it; selecting it again unpins it. Hovering
another category previews it temporarily, then returns to the pinned selection.
Legend buttons also support keyboard focus and Enter/Space. Press Escape or choose
**Clear Selection** to reset. The two charts are independent, use light/dark theme
tokens and respect reduced-motion preferences. Switching portfolios resets selection.
Displayed financial values remain formatted from the API's original decimal strings.

The detail card also lists **all current holdings** in the active category, with
backend ticker weights labeled **% of portfolio** (not % of the category). Closed
positions and metadata-only tracked securities are excluded. Unpriced holdings
remain in the list with a dash/status instead of an invented zero. When pricing
is incomplete, backend weights cover only the priced subset; a visible notice
explains that they are not weights against the full portfolio. Categories with
no priced holdings have no slice. Pin a category to scroll its complete list;
temporary previews restore the pinned list on leave. Holdings loading/failure
does not disable the chart. Portfolio changes and write-triggered refreshes reset
pins and refetch both analytics and membership without carrying old lists forward.
No new dependencies, environment variables or backend changes are required.

### Classification suggestions

On the Holdings table or holding detail page, edit **Sector** or **Industry** to
see suggestions from that same field on any holding in the selected portfolio.
Suggestions filter as you type, ignore case when matching and removing duplicates,
and omit blank values. Use the arrow keys and Enter, or click an option, to fill
the draft; select **Save** to persist it. New values remain allowed, and saving a
blank field clears it. No fixed taxonomy or other portfolio's values are included.

### Holding-level XIRR (backend)

`GET /api/v1/portfolios/{id}/holdings/{ticker}/analytics` computes this ticker's
annualized return independently of unrelated positions. It returns a nullable
decimal-string rate, typed status, valuation date/source, and quote provenance.
Closed holdings need no current quote; open holdings use their split-adjusted
remaining quantity as the terminal valuation. Synthetic snapshots and unresolved
history block returns; unknown origins, incomplete successful imports and deliberate
deletions require review and explicit confirmation before they can be acknowledged.
Missing prices/FX and undefined returns remain withheld, never replaced by zero.
Portfolio-level behavior is unchanged. See the
[response/status semantics](./backend/README.md#holding-level-money-weighted-return-xirr).

### Holding history: review, repair, and confirm

1. Select **Review History** from the Holdings table or a holding detail page.
   Compare the full active ledger with your broker records since first acquisition:
   dates, quantities, costs, fees, dividends and splits. Each row includes its
   currency, stable ID, and read-only origin: **Observed event**, **Synthetic
   snapshot**, or **Legacy / unverified**. An observed event alone is not proof of
   complete history.
2. Use **Add missing transaction** inside the review. The ticker is locked to the
   holding; choose BUY, SELL, DIVIDEND, FEE or SPLIT and enter actual source facts.
   The default currency is the portfolio base currency; change it to the event's
   currency where needed. Saving reloads the snapshot and clears acknowledgement.
3. Repair any blocking gaps. Replace synthetic opening snapshots with actual dated
   events, then follow the detail-ledger link and explicitly delete the labeled
   synthetic row so it is not counted twice. Unresolved import events require the
   existing correction API; failed/unfinished imports need repair/retry. Empty
   ledgers, missing acquisitions and invalid events cannot be confirmed away.
4. When the ledger matches your records and no blocking gaps remain, check the
   explicit completeness acknowledgement and select **Confirm History**. After the
   server confirms success, the dialog closes and the affected views refresh.
   Reopen **Review History** to inspect the saved confirmation timestamp. Errors
   and stale reviews keep the dialog open for correction; adding missing events
   also keeps it open for further review. Confirmation does not rewrite transaction
   origins or declare an entire import complete.
5. Later relevant ledger/import changes invalidate confirmation. Reload, review
   and acknowledge again. A stale review returns `409`; the UI refreshes it but
   never automatically retries confirmation. Confirmation/repairs refresh the
   affected holdings, analytics, returns and ledger views.

`GET /api/v1/portfolios/{id}/holdings/{ticker}/history` returns the active ledger,
backend blockers and an opaque review token from the same snapshot. `POST` to that
path accepts the token plus literal `confirmed: true`. Missing identities return
`404`; stale snapshots/blockers return `409`; invalid acknowledgement returns `422`.
The UI distinguishes naturally complete history from explicit timestamped
confirmation; neither supplies missing prices or guarantees a computable XIRR.

### Holding history and ledger deletion

Holdings and analytics positions include read-only `history_complete` and typed
`history_gaps` for the **History not confirmed** indicator, independent of prices
and classification. Ledger reads expose stable transaction `id`, `portfolio_id`
and `history_origin`; these identity/provenance fields are not writable through
transaction inputs. DELETE is scoped to portfolio and transaction. Success returns
`204` after commit, retains an audit tombstone and invalidates affected confirmation.
Active imports or deletions that orphan later sales return `409`, not partial writes.
See the [backend semantics](./backend/README.md#holding-history-indicators-and-transaction-deletion)
and [frontend runbook](./frontend/README.md#holding-history-and-deleting-ledger-events).

---

## Testing
Tests are written **side-by-side with code** — a change isn't done until its tests pass (see `AGENTS.md` §11).
- **Backend:** `pytest` + `pytest-asyncio` + `pytest-cov`; `backend/tests/` mirrors `backend/app/`.
  - Fast unit run (offline, default): `cd backend && uv run pytest`
  - Integration (real Postgres/pgvector, opt-in): `uv run pytest -m integration` *(requires `docker compose up -d`)*
  - Coverage: `uv run pytest --cov=app`
  - Lint & types: `uv run ruff check .` · `uv run mypy`
- **Frontend:** Vitest + React Testing Library — `cd frontend && npm run test`. Specs co-located under `src/__tests__/`; components are exercised against the typed API client with MSW mocks (no live backend). Also `npm run lint` and `npm run typecheck`.
- Financial math has exhaustive edge-case coverage; AI tests assert structure/citations, never exact LLM wording.

---

## Secrets & Configuration
- Every variable is documented in [`.env.example`](./.env.example); the real `.env` is git-ignored.
- Config is loaded centrally via `backend/app/core/config.py` (Pydantic `BaseSettings`), which reads the **root** `.env`.
- `DATABASE_URL` (e.g. `postgresql+asyncpg://postgres:postgres@localhost:5432/asset_management`) is the single knob that points the app at a database. The app connects to whatever is bound to that host/port — the Docker container publishes `localhost:5432`. To run alongside a local Postgres, change `POSTGRES_PORT` and the URL to avoid a port clash.
- Switching AI provider is **config-only** (`AI_PROVIDER` + keys) — no code changes.
- Never commit API keys, `.env`, or uploaded documents.

## Contributing / Agent Protocol

### Copilot custom agents (JetBrains)

Repository profiles live in `.github/agents/*.agent.md`; these are Markdown
instructions with YAML frontmatter, not Python packages or services to install.

- `project-orchestrator`: owns planning, API seam checks, and cross-layer delivery.
- `backend-implementer`: implements backend-only slices and runs pytest/ruff/mypy.
- `frontend-implementer`: implements frontend-only slices and runs Vitest/lint/typecheck.

Open this repository as a project in a current GitHub Copilot plugin with custom
agent support. Start a new Copilot Chat and check the agent picker for these
profiles; select `project-orchestrator` to coordinate work. If newly added profiles
are not visible, restart the IDE and check again. Delegate by the exact profile
names above; `general-purpose` is not defined by this repository.

Profile discovery and nested delegation are separate capabilities: seeing a profile
in the picker does not prove the current plugin/session can launch it as a subagent.
Validate delegation with a read-only request before assigning implementation. If the
launcher reports `Custom agent '<name>' not found`, refresh the session and verify
plugin support; do not bypass layer isolation. Where nested delegation is unavailable,
use separate chats for the backend and frontend profiles and carry the published
OpenAPI contract between them. No npm, uv, API-key, or database setup is needed just
to define the profiles; their implementation/test commands still need the normal
project prerequisites above.

- Read `STRUCTURE.md` before writing; update it whenever files or folders change.
- Keep this `README.md` runnable — update setup/run/test steps in the same change that alters them (`AGENTS.md` protocol #8).
- Ship tests in the same change as the code (`pytest` backend, Vitest frontend) — untested logic is incomplete.
- Keep business logic deterministic; AI never computes financial figures (see `AGENTS.md` §1, §7).
- Cross-module access goes through `providers/` interfaces only.
- Commit in small, logically-scoped, one-line Conventional Commits (`AGENTS.md` protocol #7). Local commits are part of delivery by default: the orchestrator stages each validated slice with its tests and required docs, commits it before the next slice, and reports actual hashes plus remaining working-tree status. Delegates hand off files and validation evidence rather than leaving commits to the user. Only an explicit user instruction defers commits; a later request to commit supersedes it. Never push or rewrite history without permission.

## Reported account snapshots (backend foundation)

Before starting an existing installation, run from `backend/`:

```bash
uv run alembic upgrade head  # head 0010: account foundations plus retirement imports/activity
uv run python -m uvicorn app.main:app --reload
```

Open <http://localhost:8000/docs> to create a portfolio with optional account type,
custodian and string external account ID (preserves leading zeros), create shared
securities, then POST/GET `/api/v1/portfolios/{id}/valuations`. The full fictitious
Swagger examples and response/status contracts are in
[the backend runbook](backend/README.md#shared-securities-and-reported-account-valuations).
Reported snapshots retain exact decimals, source provenance and nullable unknown
basis/returns without synthetic BUY events or market-data configuration. They are a
**separate reported view**, not additive balances alongside legacy ledger analytics.
Existing Robinhood imports and `/positions` behavior are unchanged. Slice 1 did not
include a CSV parser; the separate backend slice 2a workflow is now available below.

### Vanguard preview and atomic import (backend only)

After upgrading to **0010**, open <http://localhost:8000/docs>. Select a USD portfolio,
then POST multipart `file`, explicit holdings `as_of` (ISO date), `currency=USD` and
optional `history_complete=false` to
`/api/v1/portfolios/{id}/retirement-imports/preview` (200). Inspect source holdings,
activity, exact reported total, nullable mappings, typed issues and reconciliation.
Preview is read-only. Confirm by POSTing the same file/options plus its
`preview_token` and exactly `confirmed=true` to `.../retirement-imports` (201).
Read the import history/details, `.../account-activity`, and the separate reported
`.../valuations` view (all 200). See the
[backend Swagger contract and limits](backend/README.md#vanguard-retirement-imports-backend-slice-2a).

Unknown funds become UNKNOWN securities with null tickers, never guessed public
share classes. Partial activity does not add to current holdings or enable FIFO,
account return or XIRR. Unsupported historical codes remain visible and block
commit. Same-file identical rows retain multiplicity; duplicate files, ambiguous
overlapping exports, stale reviews and conflicting dates return 409. Invalid
inputs return 422, missing resources 404 and uploads over 5 MiB 413. Raw exports
stay in configured `StatementStorage`, outside Git and database blob columns.
All relational changes commit/roll back together; failed DB commits can leave only
an unreachable checksum-addressed raw file. Fixtures are entirely fictitious.

Slice 2a is backend-only; the dashboard workflow is delivered in slice 2b below.
MSW tests require no live-service dependency. Existing securities POST can pre-map an alias before import; stable
UNKNOWN/null-ticker securities are also approved import scope. Post-import security
metadata amendment, ticker identity confirmation/update and alias remapping require
an approved schema/API slice before slice 4 and look-through, not completion of
slice 2a. No speculative mapping endpoint is included.
Legacy Robinhood import and analytics remain unchanged.

## Vanguard dashboard workflow (frontend slice 2b)

With the backend migrated to **0010** and running, start `npm run dev` from
`frontend/` and open <http://localhost:3000>. No market-data or MCP setup is needed.

1. Create/select a USD portfolio. Open **Account Settings** (`/settings`), choose
   **Edit Account Settings**, set the known account type (or leave Unknown), custodian
   and string account ID, then **Save Account Settings**. Keep leading zeros; do not
   infer traditional/Roth status from a plan name. Metadata is optional before import.
2. Open **Imports** (`/imports`), select **Vanguard** under **Brokerage**, then in
   **Vanguard Retirement Import**, choose your local `.csv`, explicitly enter
   **Holdings as of date**, and retain USD. Leave **Includes All Transactions Since
   Inception** unchecked unless supported by your broker records.
3. Select **Preview Vanguard Import**. Inspect every fund, source account/plan,
   activity, mappings, issues and share reconciliation. Expand **Inspect activity**
   and individual source lines for retained facts. Unknown tickers are not guessed.
4. Check the review acknowledgement and select **Confirm Vanguard Import** only
   when the backend permits it. Success refreshes account metadata, selector metadata,
   imports and activity, and provides **View Reported Holdings** to open the balance
   page. **Inspect Import #...** reopens the persisted review/diagnostics.

Reported Holdings and Ledger Analytics are distinct pages, never summed.
Existing snapshots (including partial snapshots) and retirement account types default
into the reported view. Empty retirement accounts show an import prompt, not a zero
balance. Unknown basis, prices, P&L and returns remain unavailable. A reported
snapshot and partial activity do not establish acquisition lots, FIFO or XIRR.

409 duplicate/overlap/stale conflicts show the backend explanation and require a
new preview; file/options remain selected. Changing file, date or history assertion
invalidates review. Cancel and portfolio switches discard browser results, but an
already-submitted server commit may complete: inspect/reload persisted history
before retrying. Unsupported codes, account mismatches and date conflicts remain
backend policy, not client-side guesses.

Mock mode accepts only the fictitious `demo-retirement.csv` bytes exported as
`demoRetirementCsv` in `frontend/src/mocks/retirement-fixtures.ts`. It persists the
fixed demo workflow, not arbitrary CSV parsing. Use live mode for your real export;
never copy private account files into Git. See [the frontend runbook](frontend/README.md#vanguard-retirement-accounts-slice-2b)
for API/test details. No dependencies or backend executable files changed.

## Portfolio pages

Persistent navigation provides bookmarkable pages and preserves the selected portfolio:

| Page | URL | Purpose |
|---|---|---|
| Overview | `/` | Automatic reported-holdings or ledger view for the selected account |
| Reported Holdings | `/holdings` | Dated reported balances, separate from the ledger |
| Ledger Analytics | `/ledger` | Trade-based holdings, allocation, history and manual entry |
| Imports | `/imports` | Select Robinhood or Vanguard to display its form and history |
| Account Settings | `/settings` | Edit account type, custodian and string account ID |

Conventional non-retirement investing accounts use **Taxable Brokerage** (`TAXABLE`
in the API). Account type describes tax treatment; custodian identifies the brokerage.
Imports no longer appear beneath holdings or ledger analytics. Switching brokerage
or leaving the page discards local review/upload state, but already-submitted server
work may complete. Inspect retained history before retrying.

## Frontend Chromium browser testing

From the repository root:

```powershell
cd frontend
npm ci
npm run test:e2e:install  # download pinned Chromium
npm run test:e2e          # real browser, desktop + narrow viewport
npm run test:e2e:headed   # watch automated clicks in a visible browser
npm run test:e2e:ui       # interactive test selection and re-runs
npm run test:e2e:debug -- --project=chromium -g "feature links"
npm run test:e2e:report   # last HTML report, loopback only
```

This is **frontend browser E2E, not full-stack**: the real Next app uses existing
fictitious MSW responses, with no backend or live-account writes. The runner owns
`http://127.0.0.1:3100`, refuses existing servers, forces mocking and a same-origin
API URL regardless of local live settings, and generates the public MSW worker.
Next test build output is isolated under `.next/e2e`. No live URL override is provided.
Failure screenshots/video/traces and the HTML report are generated and git-ignored.
See [the browser runbook](frontend/README.md#chromium-browser-e2e-frontend-only)
for debugging, artifact paths and coverage limits. Terminal Playwright works now;
Playwright MCP registration is a separate optional IDE/plugin setup, not installed
or configured by this slice. No IDE MCP tools or full-stack coverage are claimed.
