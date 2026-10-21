# Frontend agent prompt: holding history and transaction deletion

Work only on the frontend of
`C:\Users\Ashi\Data\Tech\Projects\GitHub\asset-management`.
Do not edit backend code/OpenAPI or the sibling repository. Preserve existing
uncommitted work; inspect git status/diffs first. Read `AGENTS.md`, `STRUCTURE.md`,
`frontend/README.md`, and the backend contract section
`backend/README.md#holding-history-indicators-and-transaction-deletion`.
Use Windows PowerShell 5.1 syntax (semicolons, not `&&`).

## Task 1: main holdings-table history indicator

- Regenerate frontend types from the published `backend/openapi.json` using the
  frontend runbook; do not manually edit generated types or regenerate backend files.
- Holdings list/detail/classification responses and portfolio analytics positions
  now expose `history_complete: boolean` and `history_gaps: HoldingHistoryGap[]`.
- Show an accessible **History not confirmed** badge/indicator for false values in
  the main portfolio page's Holdings table. Show readable reasons in a tooltip or
  details region; do not rely solely on color or hover. Reuse on holding detail if
  useful, without adding a new backend request per table row.
- Map all reasons: `UNKNOWN_ORIGIN` (legacy origin unverified), `SNAPSHOT` (synthetic
  opening lot), `IMPORT_NOT_COMPLETE` (import not confirmed complete),
  `IMPORT_NOT_SUCCEEDED` (relevant import unfinished/failed), `UNRESOLVED_EVENTS`,
  `DELETED_TRANSACTION`, `NO_TRANSACTIONS`, and `NO_ACQUISITION`.
- Multiple reasons may coexist. Do not say every incomplete holding is a snapshot,
  claim transactions are definitely missing, or infer history status from prices,
  sector/industry gaps, or a null XIRR. True means no known history blockers under
  the backend policy, not independent verification of the owner's broker history.
- This is a read-only indicator. Do not add a completeness toggle or change origins.

## Task 2: confirmed transaction deletion

- Ledger GET `/api/v1/portfolios/{portfolio_id}/transactions` now returns
  `TransactionRecord[]`, including integer `id` and `portfolio_id` plus all existing
  financial fields. Keep read aliases distinct from transaction-create inputs;
  read-only IDs/unknown write fields are rejected with `422`.
- Use stable database IDs for keys and delete targets, never array indexes or
  ticker/date/amount matching. Identical financial transactions have different IDs.
- Add an accessible Delete action on each ledger row, including filtered holding
  ledgers if they use the same component. Show an explicit confirmation dialog with
  the selected ticker/type/date/quantity or amount and clearly labeled Cancel/Delete.
- Explain that deletion changes calculated holdings/returns, may invalidate import
  retry safety, and marks this holding's history unconfirmed. It removes the event
  from the active ledger but retains a backend audit record; no undo is provided.
- Cancel/Escape/dismiss must make no DELETE request. Guard double submission and
  show a pending state. Keep an immutable selected account/transaction identity;
  closing/cancelling on portfolio changes is preferable to targeting the new account.
- On confirmation call
  `DELETE /api/v1/portfolios/{portfolio_id}/transactions/{transaction_id}`.
  Handle `204` as success with an empty body, not JSON. Use the existing API error
  abstraction for `404`, `409`, network, and server failures.
- `404` means absent/wrong-account/already deleted. Show stale-row guidance and
  refetch; never silently delete a different row. `409` means an active account
  import or remaining sales depend on the removed BUY/SPLIT; show the backend
  explanation and leave the row intact. Do not advise bypassing this guard.
- Do not optimistically remove rows before success. After `204`, invalidate/refetch
  ledger, holdings, portfolio summary/analytics/allocations, affected holding
  analytics, and import history/retry indicators using the existing version-token
  refresh mechanism. Guard stale responses after selection changes/unmounts.
- Last-event deletion retains the backend holding/classification row but removes
  the calculated position. Handle tracked/no-active-position and empty ledger
  states without inventing zeros or claiming history is complete.

## Mocks, tests and delivery

- Update MSW fixtures/state/handlers to match OpenAPI, including stable unique IDs,
  multiple history reasons, deletion persistence/history invalidation, `204`,
  repeated-delete `404`, and conflict `409`. Do not mutate real application data.
- Add client tests for the scoped DELETE URL, bodyless `204`, and error mapping.
- Add component tests for badges/reasons, keyboard-accessible confirm/cancel,
  no request on cancellation, pending/double-click behavior, errors retaining rows,
  identical rows distinguished by ID, selected-account changes, and successful
  refresh of ledger/holdings/history/allocations/holding XIRR.
- Preserve existing classification, import and holding-XIRR functionality. No new
  transfer, reconciliation, history-confirmation or meta-portfolio feature is in scope.
- Run the frontend test/lint/type-check gates from its runbook. Update frontend
  runbooks when appropriate and `STRUCTURE.md` last, preserving backend entries.
- Backend deployment prerequisite: migration `0007` must be applied before running
  the updated API. Do not run application migrations or alter real records here.
- Summarize changes/tests and remaining integration caveats. Do not commit unless asked.
