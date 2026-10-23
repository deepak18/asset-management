# asset-management backend

FastAPI service for the Local AI-powered Investment Research Platform.

**Implemented so far (PLAN.md §1.1–1.2):**
- Deterministic portfolio calculators — allocation, FIFO cost-basis P&L, realized/unrealized, XIRR (pure, side-effect-free).
- Currency-normalization seam (`core/currency.py`) — USD now, INR-ready.
- SQLAlchemy 2.0 async models + `PortfolioProvider` interface + orchestration service.
- Alembic migrations (portfolio schema + pgvector enablement).
- REST API: `/health`, `/api/v1/portfolios/{id}` (+ `/transactions`, `/holdings`, `/analytics`). `/analytics` returns cost-basis/realized/XIRR always, and adds unrealized P&L + allocation weights (by ticker/sector/industry) when market data is available — degrading gracefully to `unpriced_tickers` otherwise.
- **Data entry & import (write endpoints):** create/list portfolios, key in transactions, record current-holding **snapshots**, or upload a broker CSV that is parsed **asynchronously** with pollable job status — see [Getting data in](#getting-data-in).
- **Holding classification:** backfill sector/industry from company profiles (`POST /holdings/classify`) or set them by hand (`PATCH /holdings/{ticker}`) — see [Known gaps & follow-ups](#4-sector--industry-classification).
- AI provider abstraction (`app/ai/`) — typed `LLMClient` interface + local Ollama adapter (`complete` / `complete_structured` / `embed`); switching provider is config-only (`AI_PROVIDER`), no code changes (§4).
- Market data (`app/marketdata/` + `app/mcp/`) — `MarketDataProvider` served by the AlphaVantage **hosted MCP** server, behind a read-through Postgres cache (TTL + stale fallback) and a free-tier throttle. Quotes/profiles/statements map to typed schemas with source provenance (§7).

## Develop (managed with `uv`)

```bash
cd backend
uv sync --extra dev --extra postgres    # see the pruning warning below
uv run pytest                           # fast, offline unit suite (integration excluded)
uv run pytest -m integration            # opt-in integration suite (needs `docker compose up -d`)
uv run pytest --cov=app                 # coverage
uv run ruff check .                     # lint
uv run mypy                             # strict type-check
```

> ⚠️ **`uv sync` prunes.** It makes the venv match *exactly* the extras you name, so
> running `uv sync --extra dev` on its own **uninstalls `asyncpg`** and the app then
> fails with `ModuleNotFoundError: No module named 'asyncpg'` if `DATABASE_URL`
> points at Postgres. Always pass both extras (`--extra dev --extra postgres`) unless
> you deliberately want the SQLite-only environment. The app detects this and tells
> you the exact command to run.

## Run against Postgres

From the **repo root** first: `docker compose up -d --wait` (starts Postgres + pgvector), then:

```bash
cd backend
uv sync --extra dev --extra postgres
uv run alembic upgrade head             # includes retirement imports/activity (0010)
uv run python -m uvicorn app.main:app --reload    # http://localhost:8000/docs
```

Config comes from the repo-root `.env` (see the main [README](../README.md)); `DATABASE_URL` selects the database. With no `.env`/env override, the app falls back to a local SQLite file for zero-infra runs.

Existing installations must also run `uv run alembic upgrade head` before restarting
the API. Revision `0005` conservatively marks existing non-null classification as
`MANUAL`; old failed/interrupted imports lack ownership tags and cannot be safely
retried automatically.

Revision `0006` is required even if `0005` has already been applied. It adds
transaction-origin tracking for holding-level returns; `0005` is unchanged.
Existing ownership-tagged import rows retain observed origin and are checked
against their job's completeness. Legacy unowned rows become `UNKNOWN`: old
snapshots and manual trades were stored identically, so guessing would fabricate
return history. This deliberately withholds holding XIRR for those rows until
history is reconciled from source records and explicitly reviewed as described below.
No existing transactions are deleted or financially changed by this migration.

Revision `0007` is required even on installations already upgraded to `0006`.
It adds nullable `transactions.deleted_at`; all existing events remain active.
Upgrade before restarting the API. Downgrading `0007` permanently removes tombstoned
events before dropping the column, so a downgrade cannot resurrect deleted trades;
back up the database before downgrading. No application migration is automatic.

> 💡 **Why `python -m uvicorn` and not `uvicorn`?** `uv sync` installs a small
> `uvicorn.exe` launcher shim in `.venv\Scripts\`. On locked-down Windows (Smart App
> Control / WDAC / AppLocker), spawning that freshly-created unsigned shim is blocked
> with `error: Failed to spawn: 'uvicorn' … An Application Control policy has blocked
> this file. (os error 4551)`. Invoking through the trusted Python interpreter
> (`python -m uvicorn …`) sidesteps the shim entirely. The same trick applies to any
> blocked console script (`python -m pytest`, `python -m alembic …`).

Revision `0008` adds nullable `holdings.history_review_token` and
`holdings.history_confirmed_at`. Existing holdings remain explicitly unconfirmed;
no ledger facts or import-wide completeness flags are rewritten. Run
`uv run alembic upgrade head` before restarting. Downgrading to `0007` removes
confirmations only, preserving holdings and transactions.

## Shared securities and reported account valuations

Revision **0009** adds account metadata and separate securities/aliases/valuation
and position tables; existing holdings, transactions and Robinhood imports are
unchanged. Run `uv run alembic upgrade head` before restarting. Downgrading to
`0008` discards only the new metadata and snapshot tables.

Start with `uv run python -m uvicorn app.main:app --reload`, then open
<http://localhost:8000/docs>. No market-data credentials are needed for this workflow:

1. `POST /api/v1/portfolios` (201), for example:
   ```json
   {"name":"Fictitious Retirement","base_currency":"USD","account_type":"TRADITIONAL_401K","custodian":"Fictitious Custodian","external_account_id":"00001234"}
   ```
   Old bodies with only name/base_currency still work. `account_type` defaults to
   `UNKNOWN`; allowed values are `UNKNOWN`, `TAXABLE`, `TRADITIONAL_401K`, `ROTH_401K`,
   `TRADITIONAL_IRA`, `ROTH_IRA`, `OTHER`. Custodian and external account ID are
   nullable strings; numeric identifiers are rejected, preserving leading zeros.
   Existing GET/list/analytics portfolio identities now include these fields.
   `PATCH /api/v1/portfolios/{id}/account` (200/404/422) preserves omitted fields;
   explicit null clears nullable strings. Empty patches and null account_type fail.
2. `POST /api/v1/securities` (201), for example:
   ```json
   {"name":"Fictitious 2050 Class A","instrument_type":"COLLECTIVE_TRUST","ticker":null,"currency":"USD","aliases":[{"source_code":"FICTITIOUS_CUSTODIAN","value":"000045"}]}
   ```
   Keep the returned immutable numeric `id`. `GET /api/v1/securities` (200) lists
   shared identities. Types: `UNKNOWN` (default), `STOCK`, `ETF`, `MUTUAL_FUND`,
   `COLLECTIVE_TRUST`, `TARGET_DATE_FUND`, `CASH`, `OTHER`. Ticker is nullable and
   is **never inferred from a name**. Names/tickers are not identity keys; explicit
   `(source_code, value)` aliases uniquely identify a security (duplicate: 409).
   Aliases are case-sensitive; the same value under a different source is distinct.
   Different fund classes must have separate IDs. With no explicit alias, a new
   identity is created each time; name matching/manual mapping is not implemented.
3. `POST /api/v1/portfolios/{id}/valuations` (201, including exact repeats), replacing
   `security_id` below with the ID from step 2:
   ```json
   {"as_of":"2026-01-31","currency":"USD","complete_snapshot":true,"source_code":"MANUAL","source_reference":"fictitious-statement:7","positions":[{"security_id":1,"quantity":"12.3456789012","reported_price":null,"reported_value":"1234.56","cost_basis":null,"source_reference":"line:7"}]}
   ```
   Date/currency/positions are required; complete_snapshot defaults true. All
   amounts must be finite, nonnegative, fit NUMERIC(28,10), and are returned as
   **Decimal strings**, not floats. Unknown securities/currency mismatches and
   duplicate positions fail with 422. Snapshot, security and portfolio currencies
   must agree: no guessed FX conversion. Source code defaults `MANUAL`; references
   are nullable. Reported value is authoritative, not quantity multiplied by price.
4. `GET /api/v1/portfolios/{id}/valuations` (200) returns a `ValuationView`:
   `view=REPORTED_SNAPSHOT`, `status=AVAILABLE|PARTIAL|EMPTY`, and nullable `snapshot`.
   A portfolio without snapshots returns EMPTY/null; missing portfolios return 404.
   Snapshot fields include id, portfolio_id, as_of, currency, complete_snapshot,
   positions, reported_total, nullable cost_basis/unrealized_pnl, and always-null
   money_weighted_return with `history_status=VALUATION_ONLY`. Position fields
   include the submitted values, nullable unrealized_pnl, the same unavailable
   return/history status, and provenance. Unknown basis stays null, including totals
   if any position lacks basis. No acquisition date is inferred. Each figure carries
   typed provenance: source_code, nullable source_reference, as_of, UTC imported_at.
   Position references override the snapshot reference for position provenance.

This is a **separate reported snapshot view**, not additional holdings to add to
legacy ledger analytics. It never writes BUY events, cash balances or holdings and
never fetches prices. `/positions` retains its old synthetic-opening-BUY behavior;
Robinhood imports and legacy analytics are unchanged. Do not combine these views
as if they were additive balances. Snapshot-only returns are explicitly unavailable.

Historical snapshots are immutable and unique per portfolio/date. Canonical hashes
ignore position order and equivalent decimal spelling, but include provenance and
completeness. An exact repeat returns the original snapshot/import time; differing
content returns 409 (no replacement endpoint). GET selects latest **as_of**, not
last import time. A partial snapshot reports only submitted positions and a partial
total, without carrying forward old rows. Empty complete snapshots report zero
holdings, not missing data. Whole snapshots commit atomically. Future import writers
can compose security and snapshot writes (and activity on that same session) inside
`async with provider.transaction():` for one commit/rollback; canonical hashing stays
in `portfolio/accounts.py`, never the provider. Vanguard uses this atomic seam below.

## Vanguard retirement imports (backend slice 2a)

Run `uv run alembic upgrade head` from `backend/` before restarting the API.
Head **0010** adds `retirement_imports` and `retirement_activity`; no legacy ledger
facts change. Downgrading to 0009 removes import/activity ownership and diagnostics,
not shared securities or reported valuation snapshots. Back up DB **and** raw storage.
No new dependency, external service, credentials or background worker is required.
The frontend workflow is not included; use <http://localhost:8000/docs>:

1. Create/select a portfolio with base currency USD. Account type defaults UNKNOWN;
   choose traditional/Roth only from actual account information. External account ID
   is a nullable **string**. If unbound, commit binds the observed raw activity account
   ID and custodian `Vanguard` atomically. Existing IDs compare after removing leading
   zeros only; genuine mismatches return 409. Existing bound metadata is not guessed.
2. `POST /api/v1/portfolios/{id}/retirement-imports/preview` (200), multipart:
   required `file`, `as_of` (ISO `YYYY-MM-DD`) and `currency` (`USD`, matching account);
   optional `history_complete` defaults false. Supply the actual holdings date:
   trade/run dates and upload time never establish a valuation date.
3. Inspect the `RetirementPreview`: `portfolio_id`, opaque `preview_token`, `options`,
   `source` (checksum, raw plan/account strings, holdings and activity), `funds`, exact
   `reported_total`, nullable/unknown basis, P&L and return, `issues`, `reconciliation`,
   `can_commit`. Unknown funds show exact names, `security_id:null`, `ticker:null`,
   `status:WILL_CREATE_UNKNOWN`. Mapped identities show `MAPPED` and nullable ticker.
   Activity-only names are included even when absent from current holdings.
4. Only when `can_commit` is true, `POST /api/v1/portfolios/{id}/retirement-imports`
   with the **same file and options**, required `preview_token`, and `confirmed` set
   to exactly the multipart text `true` (not `True`, `1` or `yes`). Success is 201,
   `RetirementImport`: `id`, `portfolio_id`, `valuation_id`, UTC `imported_at`,
   `storage_key`, `status:COMMITTED`, and persisted `preview` with resolved security IDs.
   Preview is read-only: no stored job, blob or security is created before commit.
   Commit reads back and reparses retained bytes and verifies the content checksum.
5. Read `GET .../retirement-imports` (200 array, newest import first),
   `GET .../retirement-imports/{import_id}` (200 persisted complete parsed facts and
   diagnostics), `GET .../account-activity` (200 **all** retained source activity),
   and `GET .../valuations` (latest snapshot by holdings date). Do not poll a job.
   A fund absent from the latest valuation still appears in retained activity.

All decimal facts are JSON **strings**, dates are ISO, and unknown values stay null.
`ObservedActivity` has stable `id`, `import_id`, `portfolio_id`, `security_id`,
`currency`, `source_code:VANGUARD`, and `fact`. Every source holding/activity fact
retains `checksum`, starting `source_line`, `source_reference` and `raw_fields`.
Activity also retains raw `account_number`, trade/run dates, code, description,
fund name, price, quantity, amount, kind, fingerprint, nullable
`external_contribution` and nullable `dividend_amount`. No employer/employee split
is inferred. Code 114001 is contribution information; 219004 with positive shares
is reinvestment information, with dividend dollars and units retained but **no**
external contribution inferred. Source dollars and price/quantity are independent
observations: rounded products need not agree. Current value is never counted twice.

Reconciliation per fund reports `closing_units`, nullable `net_supported_movement`,
nullable `implied_prior_units`, `status:HISTORY_INCOMPLETE|SHARES_RECONCILED|BLOCKED`,
and always `performance_calculable:false`. Implied prior units are diagnostic only.
`issues` contain enum `code`, `blocking`, nullable fund/source-line scope and message.
Partial history is explicit even when shares happen to reconcile. An assertion of
complete history requires supported activity to explain closing shares exactly;
reconciliation alone never establishes basis, cash-flow completeness or returns.
Unsupported codes are fully visible with null movement/prior units and **block**
commit; negative implied opening balances, invalid acquisitions, negative dollars
and trades after as_of also block. This is not full historical-transaction support.
No synthetic BUY, FIFO lot, cash balance, legacy holding or XIRR input is created.

Safety and limitations:

- 404: missing portfolio or scoped import. 413: upload exceeds 5 MiB.
- 422: malformed UTF-8/CSV, section/date/decimal/account structure, currency or
  confirmation. Both exact column headers are required in holdings/activity order;
  BOM, quoting, blank lines and trailing empty commas are supported. Nonfinite,
  scientific-notation, overprecision and malformed/header-like rows are refused.
  Limits: 50,000 nonblank rows (including headers), standard CSV field-size bound,
  NUMERIC(28,10), bounded identifiers/fund names. Holdings/activity sections must
  both contain rows; no inferred account for holdings-only exports.
- 409: duplicate checksum per portfolio; bound-account/plan mismatch; incompatible
  mapping/same-date snapshot; stale token; overlapping event fingerprints; blocking
  diagnostics. Review again after changing file/options/account/mappings/imports or
  valuations. Tokens cover relevant identity and persisted import/valuation state.
- Exact same-file row multiplicity is preserved. With no unique event IDs, **any**
  overlapping canonical activity fingerprint across different files is refused;
  combine nonoverlapping export periods rather than silently collapsing events.
  Same-date snapshot conflicts retain the foundation's strict immutable-content
  semantics, including source provenance; different-source assertions may conflict
  even if rounded holding values agree. No destructive replacement is available.
- Source aliases use `VANGUARD` plus `plan-account-fund:` and SHA-256 of a JSON tuple
  of normalized plan/account and the **exact** fund name. Use preview's `alias_value`
  with existing securities POST **before** import to explicitly map a known class.
  Otherwise commit creates UNKNOWN instruments with null tickers; no symbol lookup
  or public share-class guessing occurs. Different plans/classes stay distinct.
- **Required future identity work, not a slice 2a blocker:** existing securities POST
  creates immutable identities;
  duplicate aliases return 409. It cannot remap an already-created UNKNOWN alias.
  Stable UNKNOWN/null-ticker securities and explicit mappings before import are
  approved delivered import scope. Post-import security metadata amendment, ticker
  identity confirmation/update and alias remapping need a separately approved schema/API
  slice before slice 4 and look-through. This slice adds no speculative mapping
  endpoint and does not mutate financial history.
- Commit owns one relational transaction: account binding, new securities/aliases,
  whole snapshot, metadata and all activity roll back together. Preview/state checks
  repeat under the write lock. SQLite uses a write barrier; PostgreSQL locks the
  portfolio and identity tables. Live PostgreSQL contention was not tested.
  Existing single-API-process guidance remains. Failed DB commits may leave an
  unreachable checksum-addressed raw blob, but no partial ledger/import rows.
  Raw files stay behind `StatementStorage`, never in relational columns or Git.

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

## Enable market data (prices, profiles, and XIRR)

Market data is **off until an API key is present**. Set in the root `.env`:

```dotenv
ALPHAVANTAGE_API_KEY=your_free_key_here     # https://www.alphavantage.co/support/#api-key
ALPHAVANTAGE_MCP_URL=https://mcp.alphavantage.co/mcp   # already the default
MARKETDATA_CACHE_TTL_SECONDS=3600           # read-through cache; survives rate limits
```

The provider is only constructed when **both** the URL and the key are set. The URL
ships with a working default, so without that guard a key-less install would fire a
request on every analytics call that the hosted server can only reject — paying a
network round-trip to learn what configuration already knew. Unconfigured now means
an immediate, honest "not priced" instead.

Turning this on unlocks three things that are otherwise unavailable:

1. `market_value_base` / `unrealized_pnl_base` on `/analytics`,
2. allocation weights (they need market values to weight by), and
3. the money-weighted return — see [XIRR](#3-money-weighted-return-xirr-needs-a-terminal-value--and-therefore-prices).

Quotes and profiles are cached in Postgres with an `as_of` stamp and served
cache-first, so repeat requests don't consume free-tier quota.

## Getting data in

For legacy ledger analytics, there are three on-ramps below. Reported valuations
are a separate view; see [reported account valuations](#shared-securities-and-reported-account-valuations).

1. **Create a portfolio** (and list them — `GET /api/v1/portfolios` powers a UI picker)

   ```bash
   curl -X POST localhost:8000/api/v1/portfolios \
     -H 'content-type: application/json' \
     -d '{"name": "Brokerage", "base_currency": "USD"}'

   curl localhost:8000/api/v1/portfolios
   ```

2. **Snapshot current holdings** (the fast path for a 10-year-old portfolio) — assert
   the position as it stands and it is recorded as a single opening `BUY` lot, so
   cost-basis and unrealized P&L are exact. Provide **exactly one** of
   `total_cost_basis` or `cost_basis_per_share`; `as_of` is the acquisition date
   (omit it and today is stamped, but note XIRR is only meaningful with a real date).

   ```bash
   curl -X POST localhost:8000/api/v1/portfolios/1/positions \
     -H 'content-type: application/json' \
     -d '[{"ticker":"AAPL","quantity":"100","currency":"USD","as_of":"2015-06-01","total_cost_basis":"12000","sector":"Tech"}]'
   ```

3. **Enter individual transactions** (`POST /api/v1/portfolios/1/transactions`, a JSON
   array of ledger events) or **import a broker statement** (asynchronous):

   ```bash
   # 1) upload -> 202 Accepted with a PENDING job
   curl -X POST 'localhost:8000/api/v1/portfolios/1/imports?source_format=robinhood_csv' \
     -F 'file=@robinhood_activity.csv'

   # 2) poll until status is SUCCEEDED or FAILED
   curl localhost:8000/api/v1/portfolios/1/imports/1
   ```

   The uploaded file's browser-declared MIME type is untrusted, so the format is
   chosen by the `source_format` query param and the parser validates the actual
   bytes (it rejects a CSV lacking `Trans Code` / `Instrument` columns). File
   uploads require the `python-multipart` runtime dependency (already declared).

Portfolio create/transactions/positions return `201`. The import endpoint returns
`202` — see below for why.

### How statement import works (asynchronous by design)

A ten-year activity export can hold thousands of rows. Parsing and inserting all of
them inside the upload request would hold the connection open, risk proxy/browser
timeouts, and give the user a spinner with no information. So the flow is split:

1. **Accept** — `POST /portfolios/{id}/imports` validates the header, computes a
   SHA-256, writes the **raw bytes to the blob store**, creates a `PENDING` job row,
   and returns `202` immediately.
2. **Process** — a background task parses the file and inserts transactions in
   batches of `IMPORT_BATCH_SIZE`, committing each batch so `processed_rows`
   advances while the client watches. It ends `SUCCEEDED` or `FAILED` (never raises).
3. **Poll** — `GET /portfolios/{id}/imports/{job_id}` returns
   `status`, `total_rows`, `processed_rows`, `created_transactions`, `tickers`,
   `warnings`, `error`. `GET /portfolios/{id}/imports` lists the history.

Key properties:

- **Raw bytes are kept**, separately from the database. The DB stores only metadata
  plus a `storage_key`; blobs would bloat backups and can't be indexed. This makes
  re-processing possible after a parser improvement, and gives you provenance.
  Location: `STATEMENT_STORAGE_DIR` (git-ignored). The `StatementStorage` interface
  means local disk → S3 is a one-class swap.
- **Job state lives in Postgres, not memory** — progress must be readable by a
  *different* request than the one that started the work.
- **Duplicate uploads are refused (`409`).** Re-importing the same file would double
  every position and silently corrupt cost basis. Detection is by content checksum,
  scoped per portfolio. Override deliberately with `?allow_duplicate=true`.
- **Recovery:** startup marks leftover `PENDING`/`RUNNING` jobs `FAILED`, preserving
  their progress and committed rows. `POST /portfolios/{id}/imports/{job_id}/retry`
  verifies retained bytes against their checksum, removes only that job's owned
  transactions, resets the same job to `PENDING`, and returns `202` to process it
  again. Manual entries and other imports are untouched. `404` means absent,
  `409` means not failed or legacy/untracked, and `422` means bytes are unavailable
  or corrupt; failed verification never deletes partial writes.
- **Trade-off:** tasks remain in-process, not durable or automatically resumed.
  Run a **single API process**: startup recovery assumes no other process is still
  executing those jobs. Multi-worker deployment needs leases or a durable queue
  before this recovery policy is safe.

**Full history beats snapshots.** If you have the complete CSV, import it: the real
dated cash flows make the money-weighted return (XIRR) computable. A position
snapshot leaves XIRR undefined (correctly) because its opening date is asserted, not
observed.

### Robinhood CSV specifics

Export your account activity as CSV; the parser expects Robinhood's columns —
`Activity Date, Process Date, Settle Date, Instrument, Description, Trans Code,
Quantity, Price, Amount`. Notes:

- **`Activity Date` is used as the trade date** (settlement doesn't affect cost basis or XIRR).
- Rows may be newest-first; the calculators sort by date, so order doesn't matter.
- Money cells are cleaned of `$`, thousands separators, and parenthesized negatives.
- Fractional share quantities (`0.06725`) are kept exact via `Decimal`.
- Multi-line quoted `Description` cells, the trailing blank row, and the legal
  disclaimer row (which carries an extra column) are all handled.
- If `Price` is blank but `Amount` is present, the per-share price is derived as
  `|Amount| / Quantity` so the lot's cost basis is still correct.

| `Trans Code` | Result |
|---|---|
| `Buy`, `Sell` | imported as `BUY` / `SELL` |
| `CDIV` | imported as `DIVIDEND` |
| `DTAX`, `AFEE`, `DFEE` | imported as `FEE` (reduces realized P&L) |
| `SPL`, `SPR` | structured unresolved split; conservative inference only with `history_complete=true`, otherwise supply the ratio |
| `ITRF`/`ACH`/`RTP`/`WIRE` **with** an instrument + quantity | **skipped with a warning** — a transferred-in position has no price in the export; add it via the position-snapshot form so its cost basis is real, not zero |
| `ITRF`/`ACH`/`RTP`/`WIRE` cash-only | skipped (not a security transaction) |
| options (`BTO`/`STO`/`BTC`/`STC`/`OEXP`/`OASGN`), `INT`, `GOLD`, `MINT`, `REC`, `SOFF` | skipped with a warning explaining why |

Every skipped row comes back in `warnings` (with its line number, code, and
description) and `unresolved_items`, so nothing is silently lost. Dry-run a file before uploading:

```bash
uv run python scripts/import_demo.py path/to/robinhood_activity.csv
```

Transaction and position writes return `201` with a `LedgerIngestResult`.
Portfolio creation returns a `PortfolioSummary`; uploads/retries return `202`
with a `StatementImportStatus`.

## Holding history indicators and transaction deletion

### History indicators for the holdings table

`GET /api/v1/portfolios/{id}/holdings`, the single-holding GET, classification
responses, and `/analytics` positions expose:

- `history_complete: boolean`: no known history blockers under the existing
  holding-return policy. This is read-only, not independent proof that the owner
  supplied every real-world event. Manual observed purchases are user assertions.
- `history_gaps: HoldingHistoryGap[]`: deterministic, sorted reasons below.

| Reason | Meaning |
|---|---|
| `NO_TRANSACTIONS` | No active ledger events for the tracked holding |
| `NO_ACQUISITION` | Events exist but no observed acquisition can be established from a BUY |
| `UNKNOWN_ORIGIN` | Legacy/unknown provenance, or incomplete origin metadata |
| `SNAPSHOT` | At least one active synthetic snapshot opening lot |
| `IMPORT_NOT_COMPLETE` | A relevant import was not asserted complete |
| `IMPORT_NOT_SUCCEEDED` | A relevant import is pending/running/failed |
| `UNRESOLVED_EVENTS` | Relevant unresolved financial source events remain |
| `DELETED_TRANSACTION` | An event was deliberately removed from this ticker's active ledger |
| `HISTORY_CHANGED` | Saved confirmation no longer matches current ledger/import facts |
| `INVALID_LEDGER` | Invalid financial event, nonfinite/negative values, future date or oversell |

Use a neutral warning such as **History not confirmed** when false, with the
specific reasons available in a tooltip/detail. Do not assert that transactions
are actually missing, or that a holding is necessarily a snapshot. Multiple reasons
can coexist. These indicators do not fetch quotes and are separate from taxonomy
`data_gaps`, price availability, FX, and mathematical XIRR sufficiency. A complete
history can still have unavailable prices or an undefined return. Relevant imports
and unknown-ticker source issues use the same conservative scope as holding XIRR.
The holdings list loads ledger/history facts in bulk rather than calling an
analytics/quote service once per ticker.

### Review, repair, and explicitly confirm one holding

`GET /api/v1/portfolios/{portfolio_id}/holdings/{ticker}/history` returns
`HoldingHistoryReview` from one locked snapshot:

- `ticker: string` (uppercase; lookup is case-insensitive)
- `history_complete: boolean`, `history_gaps: HoldingHistoryGap[]`
- `blocking_gaps: HoldingHistoryGap[]` (cannot be acknowledged)
- `review_token: string` (opaque token; do not decode or construct it)
- `confirmed_at: datetime | null` (null without effective explicit confirmation)
- `transactions: TransactionRecord[]` (active scoped rows; Decimal values are strings)

Repair missing real events using the **existing**
`POST /api/v1/portfolios/{portfolio_id}/transactions` array contract (`201`).
Resolve tracked import source issues through the existing unresolved-item endpoint;
adding a manual event alone does not mark a tracked issue resolved. Fetch a fresh
review after every repair, deletion, or import change.

`POST` to the same holding `/history` path with
`{"review_token":"<token from GET>","confirmed":true}` returns the same review
schema (`200`). Only the actual JSON boolean `true` is accepted: false, omitted,
null, strings, and numbers return `422`. Missing portfolio/holding is `404`;
a stale or malformed string token, or any blocking gap, returns `409` without
changing confirmation. Repeating the same effective token is idempotent and keeps
the timestamp. Naturally complete history can have `confirmed_at: null`: absence
of known gaps is not an explicit attestation.

Only `UNKNOWN_ORIGIN`, `IMPORT_NOT_COMPLETE`, `DELETED_TRANSACTION`, and
`HISTORY_CHANGED` may be acknowledged. Snapshot lots, unresolved source events,
failed/pending/running relevant imports, empty/no-acquisition history, oversells,
future dates and invalid financial events remain hard blockers. Every active import
blocks even if its current ticker inventory appears unrelated; its scope is not
final. Confirmation never changes origins or an import's `history_complete`.

The persisted fingerprint covers portfolio/ticker scope, active and deleted ledger
IDs and financial payloads, origins, ownership, relevant job status/completeness,
and unresolved facts. Progress counters and job lifecycle timestamps are excluded.
Changed facts immediately make the saved confirmation ineffective on reads,
including naturally observed-complete history: `HISTORY_CHANGED` is surfaced and
`confirmed_at` becomes null until a new successful confirmation. Holdings list,
single holding, portfolio position diagnostics, and holding XIRR share this policy.
Prices, dated FX and undefined XIRR remain independently nullable; portfolio-wide
XIRR policy is unchanged.

Review and confirmation serialize with writes: SQLite uses a short write barrier;
Postgres locks portfolio (NO KEY UPDATE, permitting import foreign-key checks),
import/ledger/source tables, then scoped rows. Coarse table
locks also cover import insertion and corrections that do not take a portfolio
lock. Nonblocking acquisition inside a savepoint releases partial locks before
retrying, avoiding cycles with existing import writer orders. Trade-off:
reviews briefly serialize writes across portfolios. SQLite concurrency and mocked
Postgres contention tests are offline; live Postgres concurrency remains an
integration validation task. The existing single-API-process restriction remains.

### Ledger identity and deletion

`GET /api/v1/portfolios/{id}/transactions` now returns `TransactionRecord[]`:
the existing financial fields plus stable integer `id` and `portfolio_id`, and
required, non-null `history_origin: LedgerOrigin`. The same read-only origin is
included on every transaction in holding history review/confirmation responses:

- `OBSERVED`: a recorded manual/imported event (not independent verification).
- `SNAPSHOT`: a synthetic opening BUY created from a position snapshot.
- `UNKNOWN`: legacy provenance cannot safely distinguish a snapshot from a real trade.

Origins come directly from stored ledger facts, with no guessed default. Identify
synthetic lots by `history_origin == "SNAPSHOT"`, then use their stable IDs when
replacing/deleting them through existing guarded endpoints. Never infer snapshot
origin from dates, prices, or `UNKNOWN`; reconcile unknown rows against source
records. Confirmation preserves all origins, including `UNKNOWN`, and does not
change the canonical review-token payload or ordering. This read-contract follow-up
requires no additional migration.

Write bodies still use `Transaction`, not `TransactionRecord`; read-only IDs,
`history_origin`, and other unknown transaction input fields are rejected (`422`).
Never identify a row by its displayed index, ticker/date, or amount: identical
transactions can coexist.

`DELETE /api/v1/portfolios/{portfolio_id}/transactions/{transaction_id}`:

- `204 No Content`: deletion committed; there is no JSON success body.
- `404`: absent portfolio/transaction, wrong portfolio, or already deleted.
- `409`: an import in the account is pending/running, or deleting the event would
  leave an invalid share replay (for example, removing a BUY/SPLIT needed by a later
  SELL). Remove/correct dependent sales first; a failed request changes nothing.

The confirmation dialog belongs in the frontend. Cancel must not call DELETE.
After success, refetch the ledger, holdings, portfolio analytics, affected holding
analytics, and import history. The account and row IDs selected for confirmation
must remain bound to that request even if portfolio selection changes.

Deletion uses an audit tombstone: financial facts/origin remain stored, but all
active ledger reads and analytics exclude the deleted event. It is **not** a fake
sale and does not book proceeds. The affected holding's classification is retained;
when its last event is deleted it stays tracked, while its analytics position
disappears. Its history remains unconfirmed, including after later new entries;
deletion does not provide a history-completeness attestation or an undo operation.
Holding XIRR is withheld until permitted gaps are explicitly confirmed;
existing portfolio-level return policy/formulas remain
unchanged and simply recompute over the surviving active ledger.

Tombstone and retry-safety changes commit atomically. Deleting an owned imported
event sets that job's `retry_safe=false`; retry also explicitly refuses jobs with
owned tombstones. For unowned `UNKNOWN` legacy events, ownership is ambiguous, so
existing account import retries are conservatively disabled. Original import
counts, checksums and `history_complete` attestations remain audit facts, not counts
of surviving rows. Retained source bytes and duplicate-upload detection are unchanged;
a deliberate new duplicate-override upload is not a same-job retry and can insert
events again. Deleting a correction does not reopen its resolved source issue;
the tombstone flags the holding for reconciliation instead of silently duplicating
that correction. Restoration is not provided; holding-scoped history confirmation
is available through the review endpoint above.

This retains the existing single-API-process deployment restriction. Job row locks
coordinate deletion with existing import claims/retries on Postgres; SQLite tests
verify offline behavior, not multi-worker execution.

Frontend implementation prompt: [FRONTEND_HANDOFF.md](./FRONTEND_HANDOFF.md).

## Known gaps & follow-ups

Deliberate, documented limitations — each one is a *correct* refusal to guess
rather than a bug. They are listed in the order they distort reported numbers.

### 1. Stock splits require confirmed history or a supplied ratio

**What happens:** a Robinhood `SPL` / `SPR` row is skipped with a warning, e.g.
`row 44: skipped SPL — stock split — enter it manually with its ratio (Booking Holdings)`.

**Why:** the export reports the *shares added* (`Quantity` = `3.1736`), not the
split **ratio**. Those coincide only when you held exactly one share. Deriving the
ratio requires the pre-split open quantity at that instant — knowable only by
replaying the ledger, which the row-by-row parser deliberately does not do (a
parser that silently invents a ratio from an incomplete export would corrupt cost
basis without telling you).

**Impact if ignored:** open share count and per-share cost basis for that ticker
are wrong. Total basis stays right, so realized P&L on already-closed lots is
unaffected.

**Workaround today:** post the split yourself —

```bash
curl -X POST localhost:8000/api/v1/portfolios/1/transactions \
  -H 'content-type: application/json' \
  -d '[{"ticker":"BKNG","type":"SPLIT","trade_date":"2026-04-06","currency":"USD","split_ratio":"20"}]'
```

**Opt-in inference:** upload with `?history_complete=true` only when the file
contains complete opening history. A pure post-parse pass replays earlier rows and
accepts only near-integral forward or reciprocal reverse ratios whose share delta
agrees within `0.000001` shares. Unknown earlier events, currency mismatches,
negative/zero opening quantities, and ambiguous same-day events block inference.
This uses the export, not an independent corporate-actions feed. Uncertain cases
remain typed unresolved items; no ratio is guessed from incomplete history.

### 2. Transferred-in positions (`ITRF`) carry no cost basis

**What happens:** an `ITRF` row with an instrument and a quantity but **no price**
(an ACATS-style transfer in) is skipped with a warning pointing you at the
position-snapshot form.

**Why:** importing it as a `BUY` at a blank price would book a **zero-cost lot**,
which overstates unrealized gain by the entire value of the position. Refusing is
the only honest option — the true basis lives at the *sending* broker and is
simply not in this file.

**Impact if ignored:** those shares are missing from the portfolio entirely
(understated market value), which is visible and correctable; the alternative
(zero-cost lots) is invisible and wrong.

**Workaround today:** add each transferred-in position via
`POST /api/v1/portfolios/{id}/positions` with its real acquisition date and cost.

**Structured repair:** import jobs now include `unresolved_items` with enum `kind`,
source line, ticker, date, quantity, currency, and enum `data_gaps`. List outstanding
items with `GET /api/v1/portfolios/{id}/unresolved` (or `?include_resolved=true`).
Submit a correction to `POST /api/v1/portfolios/{id}/unresolved/{item_id}/resolve`:
use a `snapshot` for transferred shares with real cost basis, or a `transaction`
for a split/corrected event. Exactly one is required, and known source facts must
match. The correction and resolved flag commit atomically; a second submission
returns `409`, not duplicate ledger events. Gaps disappear on subsequent reads.
Use this endpoint rather than a separate snapshot write when resolving a tracked
item, so the ledger and its repair state stay consistent.

### 3. Money-weighted return (XIRR) needs a terminal value — and therefore prices

XIRR solves for the rate where the net present value of dated cash flows is zero,
which requires **at least one inflow and one outflow**. A portfolio that has only
ever bought has effectively one sign, so no root exists.

The missing flow is the **terminal value**: today's market value of the open
positions, treated as the synthetic inflow you would receive on liquidating now.
The service appends it automatically, so a buy-only imported ledger *does* produce
a return — **provided every open position can be priced**. Configure
`ALPHAVANTAGE_API_KEY` to enable that.

`/analytics` therefore returns `money_weighted_return_status` alongside the value:

| Status | `money_weighted_return` | Meaning |
|---|---|---|
| `OK` | a rate | Computed, including the terminal value (or the book is fully closed) |
| `UNPRICED_POSITIONS` | `null` | Open positions exist but at least one has no price, so the terminal value would be partial. A partial terminal value *understates* the return, so the number is withheld rather than shown wrong. Fix: configure market data. |
| `INSUFFICIENT_FLOWS` | `null` | Genuinely undefined — fewer than two distinct dated flows, or all flows share one sign. Fix: enter more history. |

A bare `null` cannot distinguish "not enough history" from "market data is off",
and those need opposite user action — hence the explicit reason.

### Holding-level money-weighted return (XIRR)

`GET /api/v1/portfolios/{portfolio_id}/holdings/{ticker}/analytics` returns a
holding-only annualized fraction. Lookup is case-insensitive; a missing portfolio
or holding returns `404`. Other unavailable results return `200` with a null
`money_weighted_return` and a typed `money_weighted_return_status`.

Response fields:

| Field | Meaning |
|---|---|
| `portfolio_id`, `ticker`, `base_currency` | Identity and the portfolio's reporting currency (not necessarily the global default) |
| `money_weighted_return` | Nullable decimal **string**; `"0.1"` means 10% annualized, not 0.1%. A genuinely flat return can be zero; unavailable is always null |
| `money_weighted_return_status` | One of the statuses below |
| `valuation_date` | Open: today's attempted terminal-flow/FX date. Closed: final ledger-event date. Withheld before replay: today's attempted valuation date |
| `valuation_source` | `QUOTE` when a usable quote was obtained (even if FX/solver later fails), `LEDGER` for closed/no-position replay, otherwise `UNAVAILABLE` |
| `valuation_provenance` | Quote's original `provider_code`, `source_table`, and `as_of`; null when no quote is used |

| Status | Meaning / action |
|---|---|
| `OK` | Computed from this ticker's observed cash flows and, if open, its terminal value |
| `INCOMPLETE_HISTORY` | Snapshot/unknown-origin rows, relevant import history not confirmed complete or not `SUCCEEDED`, or unresolved source events. Reconcile actual history; do not interpret a synthetic opening lot as a purchase |
| `UNPRICED_POSITION` | Open quantity but no configured provider or usable quote (including outage/quota, wrong-symbol, negative or future-dated quotes) |
| `MISSING_FX` | Required dated ledger or valuation FX unavailable; supply rates rather than inventing a conversion |
| `INSUFFICIENT_FLOWS` | No computable rate: insufficient distinct dated net flows/signs, or the existing solver cannot converge |
| `INVALID_HISTORY` | Impossible FIFO replay (e.g. sell before opening shares), invalid numeric inputs, or future-dated ledger events |

The service uses **only that ticker's ledger**: buys and their fees are outflows;
sells net of fees and dividends are inflows; standalone fees are outflows; splits
change open quantity but have no cash flow. FIFO replay supplies split-adjusted
remaining shares, including after partial sells. Open positions append those
shares times the last-known quote, normalized with valuation-date FX, as today's
terminal inflow. The provider/cache freshness policy is unchanged: this is not a
promise of a live quote; inspect `valuation_provenance.as_of` for its actual source
timestamp. Closed positions request **no quote** and need only historical FX.

Snapshot opening lots remain useful for basis/valuation but are **never observed
cash flows**, even with a supplied acquisition date, later sales, or when created
by transfer repair. New manual ledger entries are treated as user-asserted observed
history; the API cannot independently prove omitted trades. Imports must have been
submitted with `history_complete=true` and finished successfully, or their
incompleteness must be explicitly acknowledged through holding history review.
An earlier incomplete import is not made complete merely by resolving one issue. Any relevant
unresolved source event (even one with no `data_gaps`) prevents a trusted return.
Taxonomy gaps alone do not block XIRR.
Cash-only dividend/fee history without any observed acquisition is also incomplete,
even if the cash flows alone would admit a mathematical root.

Known unrelated tickers' missing quotes, FX, incomplete imports, and unresolved
events do not block this endpoint. An unresolved item with **unknown ticker**, or
an unfinished/failed import without a final ticker inventory, conservatively blocks
holding returns because its scope cannot be ruled out yet. Status precedence is
history completeness, ledger validation/FX, terminal price/FX, then solver outcome.
FX rates injected for another base currency are never reinterpreted as portfolio
rates; cross-currency returns remain unavailable without appropriate dated rates.

This is independent of `/portfolios/{id}/analytics`: the existing portfolio-level
calculation, statuses, and all-open-positions pricing requirement are unchanged.

### 4. Sector / industry classification

`allocation_weights` buckets any position lacking the grouping attribute under
`UNCLASSIFIED`. A broker activity export contains no classification data — it says
you bought `NFLX`, not that Netflix is a communication-services company — so every
imported holding starts with `sector = NULL`.

Two complementary fixes, both wired up:

```bash
# Backfill from company profiles (needs ALPHAVANTAGE_API_KEY; 503 without it).
# MANUAL holdings (even cleared ones) and already-classified holdings are skipped.
curl -X POST 'localhost:8000/api/v1/portfolios/1/holdings/classify'

# Re-fetch everything, overwriting existing values with the vendor's answer:
curl -X POST 'localhost:8000/api/v1/portfolios/1/holdings/classify?refresh=true'

# Manual override — always available, no market data required:
curl -X PATCH localhost:8000/api/v1/portfolios/1/holdings/NFLX \
  -H 'content-type: application/json' \
  -d '{"sector":"Communication Services","industry":"Entertainment"}'
```

**Read contract:** `GET /api/v1/portfolios/{id}/holdings/{ticker}` returns one
`HoldingInfo` (case-insensitive ticker), or `404` if absent. Holdings and analytics
positions include `classification_source: MANUAL | PROVIDER | NONE` and a
`data_gaps` array of enum values: `SECTOR`, `INDUSTRY`, `COST_BASIS`, `CURRENCY`,
`SPLIT_RATIO`, `TICKER`, `TRADE_DATE`, `QUANTITY`, `TRANSACTION`. These describe
missing facts a user can supply, not flags or parseable warning text. Missing
quotes, disabled market data, and quote-FX unavailability live in
`unpriced_tickers`, never in `data_gaps`. A valid zero cost basis is not a gap.

**Backfill policy:** `MANUAL` is always protected by default, including explicit
clears. Holdings with either taxonomy field already set are also skipped; use
manual editing or `refresh=true` to fill a partial classification. Refresh opts
into replacing both fields with a usable provider profile, clearing fields the
profile omits and setting `PROVIDER`. Failed or empty lookups preserve old values
and provenance. A new bare holding starts with `NONE`.

**Loop contract:** each request attempts at most `limit` tickers (default 25,
range 1–200) in ticker order. `remaining` counts eligible, **unattempted** tickers
after this batch, not failures. Pass the returned `next_cursor` as `after_ticker`,
keeping `refresh` unchanged, until `remaining=0` and `next_cursor=null`. For unchanged
holdings this count strictly decreases along the cursor chain even when every
lookup fails. Without a cursor, a call starts a **new sweep** and retries unresolved
tickers; repeated fresh sweeps have no decreasing-count guarantee. Concurrent
holding edits/additions can change the count; the cursor is not a snapshot token.

**Failure messages:** `503` means the provider is not configured (both URL and key
are required; URL has a default): configure `ALPHAVANTAGE_API_KEY` and
`ALPHAVANTAGE_MCP_URL`, not "wait and retry". A configured provider exhausting quota
or becoming unavailable returns `200` with the ticker in `unresolved` and a typed
`failures[].reason=PROVIDER_UNAVAILABLE`: retry later. `NO_PROFILE` means no usable
taxonomy; consider manual entry. Neither is permanently final. Repeating calls is
safe: no duplicate holdings or ledger entries. Default repeats skip successes;
refresh may change metadata if the provider's answer has changed.

**Manual edits:** `PATCH` only edits an existing holding (`404` if absent), always
sets `MANUAL`, preserves omitted fields, and clears explicitly null fields, e.g.
`{"sector":null}`. Empty bodies, whitespace-only labels, and unknown fields return
`422`. No market-data dependency is required. Persistence commits before success;
the very next `/analytics` GET computes allocations with the new labels (when
prices are available). No cached allocation or background recomputation is involved.

### 5. Remaining follow-ups

* **Frontend repair workflow.** The backend supplies typed repair items; a dedicated
  UI still needs to consume the resolution and retry endpoints.
* **Independent corporate-actions corroboration.** Split inference currently relies
  on the user-confirmed export history, not an official split feed.
* **Durable background jobs / multi-process leases.** Restart recovery permits
  explicit safe retry, but does not resume tasks or coordinate multiple API workers.

## Regenerate the OpenAPI contract

```bash
uv run python -c "import json; from pathlib import Path; from app.main import create_app; Path('openapi.json').write_text(json.dumps(create_app().openapi(), indent=2), encoding='utf-8')"
```

## Dev scripts (`scripts/`)

Runnable developer utilities — **not** part of the shipped package (hatch builds only `app/`) and excluded from the lint/type gate. Run them from `backend/` with the venv active:

```bash
uv run python scripts/portfolio_demo_1_2.py     # end-to-end deterministic-core demo (in-memory DB → provider → calculators)
uv run python scripts/import_demo.py            # create portfolio → upload CSV → analytics (in-memory; pass a path to dry-run your own export)
uv run python scripts/ollama_healthcheck.py     # diagnose an Ollama connection (reachability, models, timed completion)
```
