"""Synchronous retirement orchestration using only typed provider/storage seams."""

from hashlib import sha256

from app.portfolio.accounts import AccountConflict, AccountValidationError
from app.portfolio.vanguard import (
    ImportOptions,
    RetirementImport,
    RetirementPreview,
    parse_vanguard,
)
from app.providers.retirement_import_provider import RetirementImportProvider
from app.providers.statement_storage import StatementStorage, StatementStorageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class RetirementUploadTooLarge(Exception):
    pass


class VanguardService:
    def __init__(self, provider: RetirementImportProvider, storage: StatementStorage) -> None:
        self.provider = provider
        self._storage = storage

    @staticmethod
    def _check_size(content: bytes) -> None:
        if len(content) > MAX_UPLOAD_BYTES:
            raise RetirementUploadTooLarge(f"Statement exceeds {MAX_UPLOAD_BYTES} bytes")

    async def preview(
        self,
        portfolio_id: int,
        content: bytes,
        options: ImportOptions,
    ) -> RetirementPreview:
        self._check_size(content)
        return await self.provider.preview(portfolio_id, parse_vanguard(content), options)

    async def commit(
        self,
        portfolio_id: int,
        content: bytes,
        options: ImportOptions,
        preview_token: str,
    ) -> RetirementImport:
        # Refuse stale/blocking reviews before blob I/O; provider repeats this under its lock.
        preview = await self.preview(portfolio_id, content, options)
        if preview.preview_token != preview_token:
            raise AccountConflict("stale preview; review the file and options again")
        if not preview.can_commit:
            raise AccountConflict("preview has blocking diagnostics; commit refused")
        key = f"vanguard-{preview.source.checksum}.csv"
        try:
            await self._storage.put(key, content)
            retained = await self._storage.get(key)
        except StatementStorageError as exc:
            raise AccountValidationError("source file storage unavailable") from exc
        if sha256(retained).hexdigest() != preview.source.checksum:
            raise AccountValidationError("retained source checksum does not match uploaded bytes")
        # No raw bytes enter the database. Failed DB commits may leave an unreachable
        # immutable checksum blob, but never partial aliases, activity or ledger facts.
        return await self.provider.commit(
            portfolio_id,
            parse_vanguard(retained),
            options,
            preview_token,
            key,
        )
