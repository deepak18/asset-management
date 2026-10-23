"""Typed retirement persistence boundary; commit owns every relational write.

SQLite's write barrier and PostgreSQL portfolio/identity locks serialize review
validation with writes. Preview never takes a write barrier or persists a job.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hmac import compare_digest
from typing import Protocol

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.portfolio import models
from app.portfolio.accounts import (
    AccountConflict,
    AccountNotFound,
    AccountUpdate,
    SecurityAlias,
    SecurityCreate,
    ValuationCreate,
    ValuationPositionInput,
    canonical_snapshot_hash,
)
from app.portfolio.vanguard import (
    ActivityFact,
    FundMapping,
    ImportOptions,
    ImportState,
    ObservedActivity,
    ParsedVanguard,
    RetirementImport,
    RetirementPreview,
    build_preview,
    fund_alias,
)
from app.providers.account_provider import SqlAlchemyAccountProvider


class RetirementImportProvider(Protocol):
    async def preview(
        self,
        portfolio_id: int,
        parsed: ParsedVanguard,
        options: ImportOptions,
    ) -> RetirementPreview: ...
    async def commit(
        self,
        portfolio_id: int,
        parsed: ParsedVanguard,
        options: ImportOptions,
        preview_token: str,
        storage_key: str,
    ) -> RetirementImport: ...
    async def history(self, portfolio_id: int) -> tuple[RetirementImport, ...]: ...
    async def detail(self, portfolio_id: int, import_id: int) -> RetirementImport: ...
    async def activity(self, portfolio_id: int) -> tuple[ObservedActivity, ...]: ...


class SqlAlchemyRetirementImportProvider:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._accounts = SqlAlchemyAccountProvider(session)

    async def _portfolio(self, portfolio_id: int, *, lock: bool = False) -> models.Portfolio:
        if lock and self._session.get_bind().dialect.name == "sqlite":
            # Acquire SQLite's write reservation before reading any review facts.
            await self._session.execute(
                update(models.Portfolio)
                .where(
                    models.Portfolio.id == portfolio_id,
                )
                .values(name=models.Portfolio.name)
            )
        stmt = select(models.Portfolio).where(models.Portfolio.id == portfolio_id)
        if lock:
            stmt = stmt.with_for_update()
        row: models.Portfolio | None = await self._session.scalar(
            stmt.execution_options(populate_existing=True)
        )
        if row is None:
            raise AccountNotFound("portfolio not found")
        if lock and self._session.get_bind().dialect.name == "postgresql":
            # Existing shared-security POST does not lock a portfolio; protect mappings too.
            await self._session.execute(
                text("LOCK TABLE securities, security_aliases IN SHARE ROW EXCLUSIVE MODE")
            )
        return row

    async def _state(self, portfolio_id: int, parsed: ParsedVanguard) -> ImportState:
        portfolio = await self._portfolio(portfolio_id)
        aliases = {
            fund_alias(parsed.plan_number, parsed.account_number, name)
            for name in (
                {h.fund_name for h in parsed.holdings} | {a.fund_name for a in parsed.activity}
            )
        }
        securities = tuple(
            s
            for s in await self._accounts.list_securities()
            if any(a.source_code == "VANGUARD" and a.value in aliases for a in s.aliases)
        )
        imports = tuple(
            await self._session.scalars(
                select(models.RetirementImport.checksum)
                .where(
                    models.RetirementImport.portfolio_id == portfolio_id,
                )
                .order_by(models.RetirementImport.checksum)
            )
        )
        valuations = tuple(
            await self._session.scalars(
                select(models.AccountValuation.content_hash)
                .where(models.AccountValuation.portfolio_id == portfolio_id)
                .order_by(models.AccountValuation.as_of)
            )
        )
        fingerprints = tuple(
            await self._session.scalars(
                select(models.RetirementActivity.fingerprint)
                .where(models.RetirementActivity.portfolio_id == portfolio_id)
                .order_by(models.RetirementActivity.fingerprint)
            )
        )
        return ImportState(
            portfolio_id=portfolio_id,
            base_currency=portfolio.base_currency,
            external_account_id=portfolio.external_account_id,
            custodian=portfolio.custodian,
            account_type=portfolio.account_type,
            securities=securities,
            imports=imports,
            valuations=valuations,
            event_fingerprints=fingerprints,
        )

    async def preview(
        self,
        portfolio_id: int,
        parsed: ParsedVanguard,
        options: ImportOptions,
    ) -> RetirementPreview:
        return build_preview(parsed, options, await self._state(portfolio_id, parsed))

    @staticmethod
    def _stored(row: models.RetirementImport) -> RetirementImport:
        return RetirementImport(
            id=row.id,
            portfolio_id=row.portfolio_id,
            valuation_id=row.valuation_id,
            imported_at=row.imported_at.replace(tzinfo=UTC)
            if row.imported_at.tzinfo is None
            else row.imported_at.astimezone(UTC),
            storage_key=row.storage_key,
            preview=RetirementPreview.model_validate_json(row.preview_json),
        )

    async def commit(
        self,
        portfolio_id: int,
        parsed: ParsedVanguard,
        options: ImportOptions,
        preview_token: str,
        storage_key: str,
    ) -> RetirementImport:
        try:
            async with self._accounts.transaction():
                portfolio = await self._portfolio(portfolio_id, lock=True)
                preview = await self.preview(portfolio_id, parsed, options)
                if not compare_digest(preview.preview_token, preview_token):
                    raise AccountConflict("stale preview; review the file and options again")
                if not preview.can_commit:
                    raise AccountConflict(
                        "preview has blocking diagnostics; supply supported reconciled history"
                    )
                if portfolio.external_account_id is None:
                    await self._accounts.update_account(
                        portfolio_id,
                        AccountUpdate(
                            external_account_id=parsed.account_number,
                            custodian="Vanguard",
                        ),
                    )
                mappings: list[FundMapping] = []
                for fund in preview.funds:
                    if fund.security_id is None:
                        security = await self._accounts.create_security(
                            SecurityCreate(
                                name=fund.fund_name,
                                currency=options.currency,
                                aliases=(
                                    SecurityAlias(source_code="VANGUARD", value=fund.alias_value),
                                ),
                            )
                        )
                        fund = fund.model_copy(
                            update={"security_id": security.id, "status": "MAPPED"}
                        )
                    mappings.append(fund)
                # The committed review keeps its original token and diagnostics but resolves IDs.
                resolved = preview.model_copy(update={"funds": tuple(mappings)})
                security_ids: dict[str, int] = {}
                for mapping in mappings:
                    assert mapping.security_id is not None
                    security_ids[mapping.fund_name] = mapping.security_id
                positions: list[ValuationPositionInput] = []
                for holding in parsed.holdings:
                    security_id = security_ids[holding.fund_name]
                    positions.append(
                        ValuationPositionInput(
                            security_id=security_id,
                            quantity=holding.quantity,
                            reported_price=holding.reported_price,
                            reported_value=holding.reported_value,
                            source_reference=holding.source_reference,
                        )
                    )
                valuation = ValuationCreate(
                    as_of=options.as_of,
                    currency=options.currency,
                    positions=tuple(positions),
                    source_code="VANGUARD",
                    source_reference=f"sha256:{parsed.checksum}",
                )
                stored = await self._accounts.write_valuation(
                    portfolio_id,
                    valuation,
                    canonical_snapshot_hash(valuation),
                )
                row = models.RetirementImport(
                    portfolio_id=portfolio_id,
                    valuation_id=stored.id,
                    checksum=parsed.checksum,
                    storage_key=storage_key,
                    imported_at=datetime.now(UTC),
                    preview_json=resolved.model_dump_json(),
                )
                self._session.add(row)
                await self._session.flush()
                for fact in parsed.activity:
                    security_id = security_ids[fact.fund_name]
                    self._session.add(
                        models.RetirementActivity(
                            import_id=row.id,
                            portfolio_id=portfolio_id,
                            security_id=security_id,
                            currency=options.currency,
                            fingerprint=fact.fingerprint,
                            fact_json=fact.model_dump_json(),
                        )
                    )
                await self._session.flush()
                result = self._stored(row)
            return result
        except IntegrityError as exc:
            raise AccountConflict("concurrent import or security change; preview again") from exc

    async def history(self, portfolio_id: int) -> tuple[RetirementImport, ...]:
        await self._portfolio(portfolio_id)
        rows = await self._session.scalars(
            select(models.RetirementImport)
            .where(
                models.RetirementImport.portfolio_id == portfolio_id,
            )
            .order_by(models.RetirementImport.imported_at.desc(), models.RetirementImport.id.desc())
        )
        return tuple(self._stored(row) for row in rows)

    async def detail(self, portfolio_id: int, import_id: int) -> RetirementImport:
        await self._portfolio(portfolio_id)
        row: models.RetirementImport | None = await self._session.scalar(
            select(models.RetirementImport).where(
                models.RetirementImport.portfolio_id == portfolio_id,
                models.RetirementImport.id == import_id,
            )
        )
        if row is None:
            raise AccountNotFound("retirement import not found")
        return self._stored(row)

    async def activity(self, portfolio_id: int) -> tuple[ObservedActivity, ...]:
        await self._portfolio(portfolio_id)
        rows = await self._session.scalars(
            select(models.RetirementActivity)
            .where(
                models.RetirementActivity.portfolio_id == portfolio_id,
            )
            .order_by(models.RetirementActivity.id)
        )
        return tuple(
            ObservedActivity(
                id=row.id,
                import_id=row.import_id,
                portfolio_id=row.portfolio_id,
                security_id=row.security_id,
                currency=row.currency,
                fact=ActivityFact.model_validate_json(row.fact_json),
            )
            for row in rows
        )
