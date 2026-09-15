# asset-management backend

FastAPI service for the Local AI-powered Investment Research Platform.

**Implemented so far (PLAN.md §1.1–1.2):**
- Deterministic portfolio calculators — allocation, FIFO cost-basis P&L, realized/unrealized, XIRR (pure, side-effect-free).
- Currency-normalization seam (`core/currency.py`) — USD now, INR-ready.
- SQLAlchemy 2.0 async models + `PortfolioProvider` interface + orchestration service.
- Alembic migrations (portfolio schema + pgvector enablement).
- REST API: `/health`, `/api/v1/portfolios/{id}` (+ `/transactions`, `/holdings`, `/analytics`). `/analytics` returns cost-basis/realized/XIRR always, and adds unrealized P&L + allocation weights (by ticker/sector/industry) when market data is available — degrading gracefully to `unpriced_tickers` otherwise.
- **Data entry & import (write endpoints):** create/list portfolios, key in transactions, record current-holding **snapshots**, or upload a broker CSV that is parsed **asynchronously** with pollable job status — see [Getting data in](#getting-data-in).
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
uv run alembic upgrade head             # create tables + enable pgvector + import-job table
uv run python -m uvicorn app.main:app --reload    # http://localhost:8000/docs
```

Config comes from the repo-root `.env` (see the main [README](../README.md)); `DATABASE_URL` selects the database. With no `.env`/env override, the app falls back to a local SQLite file for zero-infra runs.

> 💡 **Why `python -m uvicorn` and not `uvicorn`?** `uv sync` installs a small
> `uvicorn.exe` launcher shim in `.venv\Scripts\`. On locked-down Windows (Smart App
> Control / WDAC / AppLocker), spawning that freshly-created unsigned shim is blocked
> with `error: Failed to spawn: 'uvicorn' … An Application Control policy has blocked
> this file. (os error 4551)`. Invoking through the trusted Python interpreter
> (`python -m uvicorn …`) sidesteps the shim entirely. The same trick applies to any
> blocked console script (`python -m pytest`, `python -m alembic …`).

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

## Getting data in

You don't have to re-key years of history to make the app useful. Everything still
lives in one ledger (the single source of truth), but there are three on-ramps:

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
- **Trade-off:** execution uses in-process background tasks, which fits a
  single-user local workstation. They do not survive a restart — an interrupted job
  stays visibly `RUNNING` rather than vanishing, because state is in the database.
  Moving to a durable worker (arq/Celery/RQ) later replaces the runner only; the job
  model, storage, and API contract stay unchanged.

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
| `SPL`, `SPR` | **skipped with a warning** — enter the split manually with its ratio |
| `ITRF`/`ACH`/`RTP`/`WIRE` **with** an instrument + quantity | **skipped with a warning** — a transferred-in position has no price in the export; add it via the position-snapshot form so its cost basis is real, not zero |
| `ITRF`/`ACH`/`RTP`/`WIRE` cash-only | skipped (not a security transaction) |
| options (`BTO`/`STO`/`BTC`/`STC`/`OEXP`/`OASGN`), `INT`, `GOLD`, `MINT`, `REC`, `SOFF` | skipped with a warning explaining why |

Every skipped row comes back in `warnings` (with its line number, code, and
description), so nothing is silently lost. Dry-run a file before uploading:

```bash
uv run python scripts/import_demo.py path/to/robinhood_activity.csv
```

All four write endpoints return `201` with a `LedgerIngestResult`
(`created_transactions`, `tickers`, `warnings`, `source_format`).

## Known gaps & follow-ups

Deliberate, documented limitations — each one is a *correct* refusal to guess
rather than a bug. They are listed in the order they distort reported numbers.

### 1. Stock splits from broker exports are skipped (needs manual entry)

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

**Recommendation:** resolve splits in a *post-parse* pass, not in the parser.
After all rows are staged, replay the ledger up to each `SPL` date, compute
`ratio = (open_qty + shares_added) / open_qty`, and emit a real `SPLIT` event —
but **only** when the ledger genuinely starts before the split date (otherwise the
opening quantity is unknown and the inference is invalid). Keep the warning as the
fallback. A corroborating `SPLITS` feed from the market-data provider would let us
verify the inferred ratio against the official one before accepting it.

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

**Recommendation:** keep the refusal, but make the follow-up actionable instead of
prose. Promote these warnings into a typed, structured payload on the import job —
a list of "unresolved items" (`kind`, `ticker`, `trade_date`, `quantity`,
`description`) — so the UI can render a *pre-filled* snapshot/split form per item
and the user just supplies the missing number. That turns each warning into a
one-click fix and removes the need to read line numbers out of a text list.

### 3. Money-weighted return (XIRR) is `None` for a buy-only portfolio

This is correct arithmetic, not a defect: XIRR solves for the rate where the net
present value of dated cash flows is zero, which requires **at least one inflow and
one outflow**. A portfolio that has only ever bought (plus a few small dividends)
has effectively one sign, so no root exists and the calculator raises rather than
returning a misleading number.

The missing piece is the **terminal value**: today's market value of the open
positions, treated as a synthetic final inflow (what you'd receive if you liquidated
now). That single flow creates the sign change and makes XIRR meaningful — and yes,
it requires live quotes, i.e. the AlphaVantage MCP provider (see below).

### 4. Sector / industry allocation is all `UNCLASSIFIED`

`allocation_weights` buckets any position lacking the grouping attribute under
`UNCLASSIFIED`. Sector and industry live on the `holdings` row, and the CSV import
only ever learns a **ticker** — a Robinhood activity export contains no
classification data. So every imported holding has `sector = NULL`.

Two complementary fixes, both already supported by the existing seams:
`MarketDataProvider.get_company_profile()` returns `sector`/`industry`, and
`PortfolioWriter.upsert_holding()` persists them without overwriting values you
set by hand.

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

