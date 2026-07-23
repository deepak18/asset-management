# asset-management backend

FastAPI service for the Local AI-powered Investment Research Platform.

This turn implements the **deterministic portfolio core** (PLAN.md §1.2): pure,
side-effect-free financial calculators (allocation, cost-basis P&L, XIRR) plus a
currency-normalization seam. No DB / API / AI / providers yet.

## Develop (managed with `uv`)

```bash
cd backend
uv sync --extra dev             # create venv + install deps
uv run pytest                   # fast, offline unit suite (integration excluded)
uv run pytest -m integration    # opt-in integration suite
uv run pytest --cov=app         # coverage
```
