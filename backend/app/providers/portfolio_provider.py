"""SQLAlchemy-backed implementation of the portfolio provider interfaces.

The single responsibility here is **translation**: turn ORM rows into the frozen
Pydantic domain objects (``Transaction``, ``HoldingInfo``, ``PortfolioSummary``) that
the calculators consume, and turn typed write inputs back into ORM rows. No financial
math lives in this layer — it only reads, maps, and persists. That keeps the storage
concern isolated behind the provider boundary.
"""

from __future__ import annotations

from asyncio import sleep
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio import models
from app.portfolio.history import (
    HistoryConfirmationConflict,
    TransactionDeletionConflict,
    blocking_history_gaps,
    confirmation_is_effective,
    history_review_token,
    holding_history_gaps,
    validate_share_replay,
)
from app.portfolio.schemas import (
    ClassificationSource,
    HistoryImportState,
    HistoryTransactionState,
    HoldingHistoryReview,
    HoldingHistorySnapshot,
    HoldingImportHistory,
    HoldingInfo,
    HoldingLedger,
    ImportStatus,
    LedgerOrigin,
    PortfolioCreate,
    PortfolioSummary,
    SnapshotTransaction,
    StatementImportStatus,
    Transaction,
    TransactionRecord,
)
from app.providers.statement_import_store import SqlAlchemyStatementImportStore


class SqlAlchemyPortfolioProvider:
    """Reads *and writes* portfolio data via an injected async session.

    Satisfies both ``PortfolioProvider`` (read) and ``PortfolioWriter`` (write)
    structurally — the two Protocols exist to segregate capability at call sites,
    not to force two classes over one table set.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_portfolio(self, portfolio_id: int) -> PortfolioSummary | None:
        row = await self._session.get(models.Portfolio, portfolio_id)
        if row is None:
            return None
        return PortfolioSummary(id=row.id, name=row.name, base_currency=row.base_currency)

    async def list_portfolios(self) -> list[PortfolioSummary]:
        stmt = select(models.Portfolio).order_by(models.Portfolio.id)
        rows = (await self._session.scalars(stmt)).all()
        return [
            PortfolioSummary(id=row.id, name=row.name, base_currency=row.base_currency)
            for row in rows
        ]

    async def list_transactions(self, portfolio_id: int) -> list[Transaction]:
        stmt = (
            select(models.Transaction)
            .where(
                models.Transaction.portfolio_id == portfolio_id,
                models.Transaction.deleted_at.is_(None),
            )
            .order_by(models.Transaction.trade_date, models.Transaction.id)
        )
        rows = (await self._session.scalars(stmt)).all()
        return [
            Transaction(
                ticker=row.ticker,
                type=row.type,
                trade_date=row.trade_date,
                currency=row.currency,
                quantity=row.quantity,
                price=row.price,
                fees=row.fees,
                amount=row.amount,
                split_ratio=row.split_ratio,
            )
            for row in rows
        ]

    async def list_holdings(self, portfolio_id: int) -> list[HoldingInfo]:
        stmt = (
            select(models.Holding)
            .where(models.Holding.portfolio_id == portfolio_id)
            .order_by(models.Holding.ticker)
        )
        rows = (await self._session.scalars(stmt)).all()
        jobs = await SqlAlchemyStatementImportStore(self._session).list_jobs(portfolio_id)
        by_ticker: dict[str, list[models.Transaction]] = defaultdict(list)
        for txn in await self._ledger_rows(portfolio_id):
            by_ticker[txn.ticker].append(txn)
        return [
            _holding_info(row, _holding_ledger(row.ticker, by_ticker[row.ticker], jobs, row), jobs)
            for row in rows
        ]

    async def get_holding(self, portfolio_id: int, ticker: str) -> HoldingInfo | None:
        stmt = select(models.Holding).where(
            models.Holding.portfolio_id == portfolio_id,
            models.Holding.ticker == ticker.upper(),
        )
        row = (await self._session.scalars(stmt)).first()
        if row is None:
            return None
        jobs = await SqlAlchemyStatementImportStore(self._session).list_jobs(portfolio_id)
        ledger = _holding_ledger(
            row.ticker, await self._ledger_rows(portfolio_id, row.ticker), jobs, row,
        )
        return _holding_info(row, ledger, jobs)

    async def get_holding_ledger(self, portfolio_id: int, ticker: str) -> HoldingLedger:
        holding = await self._session.scalar(select(models.Holding).where(
            models.Holding.portfolio_id == portfolio_id,
            models.Holding.ticker == ticker.upper(),
        ))
        jobs = await SqlAlchemyStatementImportStore(self._session).list_jobs(portfolio_id)
        return _holding_ledger(
            ticker.upper(), await self._ledger_rows(portfolio_id, ticker), jobs, holding,
        )

    async def _lock_history(self, portfolio_id: int) -> bool:
        # Portfolio -> jobs -> ledger rows. Table locks also protect absent jobs:
        # the existing import store can insert/update without a portfolio lock.
        # PostgreSQL's coarse lock is deliberately short-lived and local-first;
        # SQLite's no-op UPDATE provides its equivalent database write barrier.
        if self._session.get_bind().dialect.name == "sqlite":
            await self._session.execute(update(models.Portfolio).where(
                models.Portfolio.id == portfolio_id,
            ).values(id=models.Portfolio.id))
        portfolio = await self._session.scalar(select(models.Portfolio).where(
            models.Portfolio.id == portfolio_id,
        ).with_for_update(key_share=True))
        # NO KEY UPDATE still serializes manual/deletion writers but permits
        # import inserts to finish their portfolio foreign-key KEY SHARE check.
        # FOR UPDATE here could strand a NOWAIT retry behind that FK check.
        if portfolio is None:
            return False
        if self._session.get_bind().dialect.name == "postgresql":
            while True:
                try:
                    # Imports touch these tables in several orders. NOWAIT plus
                    # savepoint rollback releases partial table locks before we
                    # wait, avoiding a cycle with a correction or retry writer.
                    async with self._session.begin_nested():
                        await self._session.execute(text(
                            "LOCK TABLE statement_imports, transactions, import_unresolved_items "
                            "IN SHARE ROW EXCLUSIVE MODE NOWAIT"
                        ))
                    break
                except DBAPIError as exc:
                    if getattr(exc.orig, "sqlstate", None) != "55P03":
                        raise
                    await sleep(0.01)
        await self._session.scalars(select(models.StatementImport).where(
            models.StatementImport.portfolio_id == portfolio_id,
        ).order_by(models.StatementImport.id).with_for_update()
          .execution_options(populate_existing=True))
        return True

    async def get_history_review(
        self, portfolio_id: int, ticker: str,
    ) -> HoldingHistoryReview | None:
        return await self._review_history(portfolio_id, ticker, None)

    async def confirm_history(
        self, portfolio_id: int, ticker: str, review_token: str,
    ) -> HoldingHistoryReview | None:
        return await self._review_history(portfolio_id, ticker, review_token)

    async def _review_history(
        self, portfolio_id: int, ticker: str, token: str | None,
    ) -> HoldingHistoryReview | None:
        try:
            if not await self._lock_history(portfolio_id):
                await self._session.rollback()
                return None
            holding = await self._session.scalar(select(models.Holding).where(
                models.Holding.portfolio_id == portfolio_id,
                models.Holding.ticker == ticker.upper(),
            ).with_for_update().execution_options(populate_existing=True))
            if holding is None:
                await self._session.rollback()
                return None
            jobs = await SqlAlchemyStatementImportStore(self._session).list_jobs(portfolio_id)
            rows = await self._ledger_rows(portfolio_id, holding.ticker)
            ledger = _holding_ledger(holding.ticker, rows, jobs, holding)
            if token is not None:
                if token != ledger.review_token:
                    raise HistoryConfirmationConflict("History changed; fetch a fresh review")
                if blocking_history_gaps(holding_history_gaps(ledger)):
                    raise HistoryConfirmationConflict("History contains blocking gaps")
                if not confirmation_is_effective(ledger):
                    holding.history_review_token = token
                    holding.history_confirmed_at = datetime.now(UTC)
                ledger = _holding_ledger(holding.ticker, rows, jobs, holding)
            gaps = holding_history_gaps(ledger)
            assert ledger.review_token is not None
            confirmed_at = ledger.confirmed_at if confirmation_is_effective(ledger) else None
            if confirmed_at is not None and confirmed_at.tzinfo is None:
                confirmed_at = confirmed_at.replace(tzinfo=UTC)
            review = HoldingHistoryReview(
                ticker=holding.ticker, history_complete=not gaps, history_gaps=gaps,
                blocking_gaps=blocking_history_gaps(gaps), review_token=ledger.review_token,
                confirmed_at=confirmed_at,
                transactions=tuple(TransactionRecord.model_validate(row, from_attributes=True)
                                   for row in rows if row.deleted_at is None),
            )
            await self._session.commit()
            return review
        except Exception:
            await self._session.rollback()
            raise

    async def _ledger_rows(
        self, portfolio_id: int, ticker: str | None = None,
    ) -> Sequence[models.Transaction]:
        stmt = select(models.Transaction).where(models.Transaction.portfolio_id == portfolio_id)
        if ticker is not None:
            stmt = stmt.where(models.Transaction.ticker == ticker.upper())
        return (await self._session.scalars(
            stmt.order_by(models.Transaction.trade_date, models.Transaction.id)
            .execution_options(populate_existing=True)
        )).all()

    async def list_transaction_records(self, portfolio_id: int) -> list[TransactionRecord]:
        return [
            TransactionRecord.model_validate(row, from_attributes=True)
            for row in await self._ledger_rows(portfolio_id) if row.deleted_at is None
        ]

    async def delete_transaction(self, portfolio_id: int, transaction_id: int) -> bool:
        try:
            # Serialize deletes within the account; job locks coordinate with
            # import claims/retries before a row can become user-edited history.
            portfolio = await self._session.scalar(
                select(models.Portfolio).where(
                    models.Portfolio.id == portfolio_id,
                ).with_for_update()
            )
            if portfolio is None:
                await self._session.rollback()
                return False
            jobs = (await self._session.scalars(
                select(models.StatementImport).where(
                    models.StatementImport.portfolio_id == portfolio_id,
                ).order_by(models.StatementImport.id).with_for_update()
            )).all()
            row = await self._session.scalar(select(models.Transaction).where(
                models.Transaction.id == transaction_id,
                models.Transaction.portfolio_id == portfolio_id,
                models.Transaction.deleted_at.is_(None),
            ).with_for_update())
            if row is None:
                await self._session.rollback()
                return False
            if any(job.status in (ImportStatus.PENDING, ImportStatus.RUNNING) for job in jobs):
                raise TransactionDeletionConflict(
                    "Wait for pending/running imports before deleting"
                )
            remaining = [
                Transaction.model_validate(event, from_attributes=True)
                for event in await self._ledger_rows(portfolio_id, row.ticker)
                if event.deleted_at is None and event.id != row.id
            ]
            validate_share_replay(remaining)
            row.deleted_at = datetime.now(UTC)
            for job in jobs:
                if job.id == row.import_job_id or (
                    row.import_job_id is None and row.history_origin == LedgerOrigin.UNKNOWN
                ):
                    # Unowned legacy rows cannot safely be assigned to a job;
                    # disable account import retries conservatively in that case.
                    job.retry_safe = False
            await self._session.commit()
            return True
        except Exception:
            await self._session.rollback()
            raise

    # --- writes -----------------------------------------------------------

    async def create_portfolio(self, data: PortfolioCreate) -> PortfolioSummary:
        row = models.Portfolio(name=data.name, base_currency=data.base_currency.upper())
        self._session.add(row)
        await self._session.flush()  # assigns row.id
        await self._session.commit()
        return PortfolioSummary(id=row.id, name=row.name, base_currency=row.base_currency)

    async def add_transactions(self, portfolio_id: int, transactions: Sequence[Transaction]) -> int:
        await self._session.scalar(select(models.Portfolio).where(
            models.Portfolio.id == portfolio_id,
        ).with_for_update())
        rows = [
            models.Transaction(
                portfolio_id=portfolio_id,
                ticker=txn.ticker.upper(),
                type=txn.type,
                trade_date=txn.trade_date,
                currency=txn.currency.upper(),
                quantity=txn.quantity,
                price=txn.price,
                fees=txn.fees,
                amount=txn.amount,
                split_ratio=txn.split_ratio,
                history_origin=(
                    LedgerOrigin.SNAPSHOT if isinstance(txn, SnapshotTransaction)
                    else LedgerOrigin.OBSERVED
                ).value,
            )
            for txn in transactions
        ]
        self._session.add_all(rows)
        await self._session.commit()
        return len(rows)

    async def upsert_holding(
        self,
        portfolio_id: int,
        ticker: str,
        sector: str | None = None,
        industry: str | None = None,
        *,
        classification_source: ClassificationSource | None = None,
        clear_fields: tuple[str, ...] = (),
    ) -> None:
        ticker = ticker.upper()
        stmt = select(models.Holding).where(
            models.Holding.portfolio_id == portfolio_id,
            models.Holding.ticker == ticker,
        )
        existing = (await self._session.scalars(stmt)).first()
        if existing is None:
            self._session.add(
                models.Holding(
                    portfolio_id=portfolio_id,
                    ticker=ticker,
                    sector=sector,
                    industry=industry,
                    classification_source=(
                        classification_source
                        or (
                            ClassificationSource.MANUAL
                            if sector or industry
                            else ClassificationSource.NONE
                        )
                    ).value,
                )
            )
        else:
            # Only overwrite with a real value; never blank out prior classification.
            if sector is not None:
                existing.sector = sector
            if industry is not None:
                existing.industry = industry
            if "sector" in clear_fields:
                existing.sector = None
            if "industry" in clear_fields:
                existing.industry = None
            if classification_source is not None:
                existing.classification_source = classification_source.value
            elif sector is not None or industry is not None:
                existing.classification_source = ClassificationSource.MANUAL.value
        await self._session.commit()


def _holding_ledger(
    ticker: str, rows: Sequence[models.Transaction], jobs: Sequence[StatementImportStatus],
    holding: models.Holding | None = None,
) -> HoldingLedger:
    owned_jobs = {row.import_job_id for row in rows if row.import_job_id is not None}
    relevant = [
        job for job in jobs
        if job.id in owned_jobs or ticker in (symbol.upper() for symbol in job.tickers)
        or any(item.ticker is None or item.ticker.upper() == ticker
               for item in job.unresolved_items)
        or job.status in (ImportStatus.PENDING, ImportStatus.RUNNING)
        or (job.status != ImportStatus.SUCCEEDED and not job.tickers)
    ]
    snapshot = HoldingHistorySnapshot(
        portfolio_id=holding.portfolio_id if holding is not None else (
            rows[0].portfolio_id if rows else 0
        ),
        ticker=ticker,
        transactions=tuple(HistoryTransactionState.model_validate(row, from_attributes=True)
                           for row in rows),
        imports=tuple(HistoryImportState(
            id=job.id, portfolio_id=job.portfolio_id, status=job.status,
            history_complete=job.history_complete, tickers=job.tickers,
            unresolved_items=job.unresolved_items,
        ) for job in relevant),
    )
    active = [row for row in rows if row.deleted_at is None]
    return HoldingLedger(
        transactions=tuple(
            TransactionRecord.model_validate(row, from_attributes=True) for row in active
        ),
        origins=tuple(LedgerOrigin(row.history_origin) for row in active),
        imports=tuple(HoldingImportHistory(
            status=job.status, history_complete=job.history_complete,
        ) for job in relevant),
        has_unresolved_events=any(
            not item.resolved and (item.ticker is None or item.ticker.upper() == ticker)
            for job in relevant for item in job.unresolved_items
        ),
        has_deleted_transactions=any(row.deleted_at is not None for row in rows),
        review_token=history_review_token(snapshot),
        saved_review_token=holding.history_review_token if holding is not None else None,
        confirmed_at=holding.history_confirmed_at if holding is not None else None,
    )


def _holding_info(
    row: models.Holding, ledger: HoldingLedger, jobs: Sequence[StatementImportStatus],
) -> HoldingInfo:
    gaps = holding_history_gaps(ledger)
    return HoldingInfo(
        ticker=row.ticker, sector=row.sector, industry=row.industry,
        classification_source=ClassificationSource(row.classification_source),
        history_complete=not gaps, history_gaps=gaps,
        data_gaps=tuple(sorted({
            gap for job in jobs if job.status == ImportStatus.SUCCEEDED
            for item in job.unresolved_items if not item.resolved and item.ticker == row.ticker
            for gap in item.data_gaps
        })),
    )
