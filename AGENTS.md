# AGENTS.md

## Project Vision & Architecture
Local AI-powered Investment Research Platform. Designed to run locally using Ollama for inference while supporting independent deployment of the frontend, backend API, and individual Model Context Protocol (MCP) servers.

This is an analytical terminal (similar to Bloomberg, NotebookLM, or Koyfin), **NOT** a casual conversational chatbot. The AI is treated as an isolated, asynchronous processing subsystem, not the core controller of the application.

---

## Coding Agent Operational Protocol (Context Management)
To prevent context window bloat and code regressions, the coding agent MUST strictly adhere to the following file-tracking protocol:

1. **The Single Source of Truth:** A file named `STRUCTURE.md` must live in the root directory, detailing the exact directory tree, active files, and short single-sentence descriptions of what each file executes.
2. **Read Before Write:** Before modifying or generating any code, the agent must read `STRUCTURE.md` to understand the current architecture boundaries.
3. **Incremental Maintenance:** Immediately after creating or altering any file or folder, the agent's final task in that turn is to update `STRUCTURE.md` to reflect the changes precisely.
4. **Context Isolation:** The agent must refuse to generate backend core code and frontend UI components in the same chat turn. Keep workflows strictly isolated.
5. **Tests Are Not Optional:** Every turn that adds or changes executable logic MUST include the corresponding tests in the *same* turn (`pytest` for backend, the frontend test runner for UI). Code delivered without tests is considered incomplete. New files/folders under `tests/` must be reflected in `STRUCTURE.md` per rule 3.
6. **Explain-As-You-Build (Pedagogical Mandate):** This project is a learning vehicle, not just a deliverable. The maintainer is upskilling as the system grows, so the agent MUST teach while it builds — behaving like a **senior peer walking a colleague through the work**, not a code-dispensing black box.
   - **Narrate the "what" and the "why," not just the "how."** For every non-trivial change, explain the technology/tooling involved (e.g., what `uv` does, how `pyproject.toml` tables are consumed, what `hatchling` builds, what `ruff`/`mypy` enforce, what `conftest.py` fixtures inject), the workflow it participates in, and the reasoning behind design/schema decisions (e.g., `Decimal` vs `float`, frozen models, separating input vs. result schemas).
   - **Surface trade-offs and alternatives.** When a choice was made (FIFO vs. LIFO, one module vs. a package split, Newton–Raphson vs. bisection), state what was chosen and why, and what the alternative would cost.
   - **Answer conceptual questions inline.** Treat "why is this named this?" / "shouldn't we do X?" as first-class work, not a distraction — clear up misconceptions explicitly.
   - **Keep explanations proportional.** Deep on new/unfamiliar concepts; brief on routine repetition. Never dump prose in place of doing the work — explanation accompanies the implementation, it does not replace it.

---

## Core Design Principles

### 1. AI Under No Circumstances Contains Business Logic
The LLM should only summarize, explain, compare, extract data patterns, generate reports, and answer contextual questions. All financial mathematics, portfolio performance tracking (TWRR/MWRR), sector weight calculations, and time-series aggregations must be executed in deterministic Python code.

### 2. Mandatory Data Layer Abstraction
Never call external endpoints, database engines, or MCP servers directly from core business logic. All interactions must pass through strongly-typed provider interfaces.
* `PortfolioProvider`: Interacts with the local DB ledger.
* `MarketDataProvider`: Fetches pricing and corporate structures (e.g., via AlphaVantage MCP).
* `CompetitorMatrixEngine`: Resolves peer groups and fetches overlapping metrics.
* `SECProvider`: Pulls regulatory filings.
* `NewsStreamingEngine`: Aggregates and streams real-time news/macro updates.
* `DocumentProvider`: Processes locally uploaded vector data.

### 3. Highly Decoupled Module Boundary
The codebase must be strictly organized into self-contained directories. Cross-module imports must happen via interfaces to allow decoupled refactoring:
* `/portfolio` - Ledger tracking, allocation computations, performance metrics.
* `/research` - Competitor analysis, news streaming engines, evaluation workspaces.
* `/documents` - Document ingestion pipelines, parsing, and vector ingestion.
* `/workspace_panel` - Context-aware AI communication framework.
* `/marketdata` - Core pricing and fundamental statement normalization layers.

### 4. Complete AI Provider Interchangeability
The underlying LLM client must be abstracted behind an interface. Switching between Ollama (default local setup) and external cloud infrastructure (OpenAI, Anthropic, Gemini) must change configuration values only, requiring zero modifications to business or agent logic.

### 5. MCP-First Integration Standard
Model Context Protocol (MCP) is the primary method for extending the AI's data visibility. The architecture must natively orchestrate calls to:
* AlphaVantage MCP Server (Market data & fundamental indicators)
* SEC EDGAR MCP Server (Regulatory statements)
* Filesystem & Browser MCP Servers (Local workflows)

### 6. Complex Workflows Managed via Directed Graphs
Simple, single-turn extractions should use PydanticAI tools directly. Any iterative, multi-step, or critical multi-document analysis workflow (such as a full Equity Research Report) must be explicitly managed as a LangGraph state machine with strict structural state definitions.

### 7. Zero-Trust AI Output & Deterministic Citations
The AI engine must never be permitted to state a financial figure unsupported by source metadata. Every numerical metric surfaced by an agent loop must contain strict citation tags linking back to either the specific section of an uploaded document, a precise line item in an SEC filing, or a structured data packet returned by an MCP server.

### 8. Total Strong Typing Enforcement
Dictionaries or generic `Any` types are forbidden for structural data transfers. All API payloads, service parameters, and internal data structures must be governed by Pydantic models, SQLAlchemy 2.0 mapped schemas, or explicit Python TypedDicts.

### 9. Independent Frontend & API Separation
The frontend interacts with the system exclusively through a decoupled REST API. There are no direct database or execution context connections between the client browser and the Python backend processing engine.

### 10. Cloud-Ready Architecture Boundary
Although optimized to run completely on a local workstation, the container boundaries must be constructed such that the Frontend, FastAPI Backend, PostgreSQL DB, and individual MCP orchestration containers can be deployed independently to a cloud environment (e.g., AWS ECS or Kubernetes).

### 11. Test-Alongside-Code Discipline
Every unit of executable logic ships with its tests in the same change — no separate "testing later" phase.
* **Backend:** `pytest` (with `pytest-asyncio` for async paths). `tests/` mirrors the `app/` package layout one-to-one.
* **Deterministic core first:** Financial math (§1) — cost-basis P&L, realized/unrealized returns, XIRR, allocation weights, FX normalization — must have exhaustive unit tests covering edge cases (empty ledgers, partial sells, splits, dividends, mixed currencies, zero/negative flows). These are pure functions and have **no excuse** for missing coverage.
* **Provider boundaries (§2) are mocked:** Unit tests never hit real DBs, external endpoints, or MCP servers — provider interfaces are stubbed/faked so domain logic is tested in isolation. Live integrations get separate, clearly marked integration tests.
* **AI is non-deterministic — test the scaffolding, not the prose:** Assert on structured output schemas, tool-call routing, citation presence/shape (§7), and graph state transitions (§6) — never on exact LLM wording.
* **Citations are enforced by tests:** For every code path that surfaces a financial figure, a test must assert a valid, correctly-typed citation is attached (see the polymorphic citation schema in `PLAN.md`).
* **Regression gate:** A change is "done" only when the relevant suite passes. Fix or explicitly quarantine (with a reason) failing tests before ending the turn.

### 12. Pythonic Module Cohesion (Not One-Class-Per-File)
Code is organized by **cohesion and responsibility**, following Python idiom — **not** the Java/C# "one public class per file" rule. A module (`.py`) groups tightly-related types that form a single concept.
* **Group what belongs together:** e.g. `core/currency.py` legitimately holds `Money`, `FxRate`, `FxRateTable`, and `MissingFxRateError` because they are one concept ("currency normalization"). Splitting them into four files would only add import churn and circular-import risk. The standard library sets the precedent (`datetime` exposes `date`/`time`/`datetime`/`timedelta`; `decimal`, `pathlib`, `dataclasses` bundle related types).
* **Split by responsibility or size, not by class count:** promote a module to a package (`currency/` with `models.py`, `table.py`, `errors.py`) only when it grows a *second distinct responsibility* or becomes large/hard to navigate (rough guide: >300–500 lines) — never merely because it contains more than one class.
* **What is actually enforced:** strong typing (§8 — Pydantic models / dataclasses / TypedDicts, never bare dicts or `Any`) and decoupled cross-**module** boundaries via provider interfaces (§2/§3). These are the real structural contracts; file granularity serves readability, not a rigid rule.
