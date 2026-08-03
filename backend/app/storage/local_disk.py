"""Local-disk implementation of :class:`StatementStorage`.

The default blob store for a single-workstation deployment: raw uploads land in a
configured directory, one file per import. Swapping in S3/MinIO later means writing
another class with the same two methods — no caller changes.

Two details worth calling out:

* **Keys are sanitized, never trusted.** A storage key derives from a checksum we
  compute, but we still reject path separators and traversal segments. A key that
  could contain ``../`` would let an upload write anywhere on the filesystem.
* **Disk I/O runs in a thread.** ``open().write()`` is blocking; calling it directly
  inside an async handler would stall the event loop for the duration of the write.
  ``asyncio.to_thread`` moves it off the loop so the server stays responsive.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.providers.statement_storage import StatementStorageError


class LocalDiskStatementStorage:
    """Store raw statement bytes as files under a base directory."""

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)

    def _resolve(self, key: str) -> Path:
        """Map a key to a path inside the base directory, rejecting traversal."""

        if not key or "/" in key or "\\" in key or key in {".", ".."}:
            raise StatementStorageError(f"invalid storage key: {key!r}")
        return self._base / key

    async def put(self, key: str, data: bytes) -> None:
        path = self._resolve(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temp file then replace: a crash mid-write can never leave
            # a half-written statement that would later import a truncated ledger.
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(path)

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            raise StatementStorageError(f"could not write {key!r}: {exc}") from exc

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            raise StatementStorageError(f"could not read {key!r}: {exc}") from exc
