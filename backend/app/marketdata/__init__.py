"""Market-data domain (PLAN.md §1.3): pricing + fundamentals behind a provider.

This package holds the *typed* market-data layer:

* ``schemas``  — frozen Pydantic carriers for quotes, company profiles, and
  normalized financial statements, each stamped with source provenance.
* ``models`` / ``cache`` — the mandatory read-through Postgres cache that shields
  us from free-tier rate limits (network is the last resort, not the hot path).
* ``errors``  — typed failures raised at the market-data boundary.

The actual upstream fetch (AlphaVantage via MCP) is a separate adapter behind
``providers.MarketDataProvider`` (§2) and is wired in a later slice; nothing here
talks to the network directly.
"""

