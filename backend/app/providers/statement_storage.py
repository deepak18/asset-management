"""Provider interface for raw statement (blob) storage.

Why file storage is separated from database metadata
----------------------------------------------------
An uploaded statement has two very different halves:

* the **raw bytes** — large, opaque, write-once, read-rarely; and
* the **metadata** — small, queryable, frequently read (status, counts, checksum).

Putting blobs in the relational database bloats backups, makes migrations slow,
and forces the DB to stream binary it cannot index or query. So bytes go to a blob
store and the database keeps only a *pointer* (``storage_key``) plus metadata. The
two halves are then independently scalable and independently backed up.

Keeping this behind a ``Protocol`` is what makes local disk → S3 → any object store
a one-class substitution: nothing in the import pipeline knows where bytes live, it
only knows ``put``/``get``. Business code depends on this interface, never on
``pathlib`` or ``boto3``.
"""

from __future__ import annotations

from typing import Protocol


class StatementStorageError(OSError):
    """Raised when raw statement bytes cannot be written or read back."""


class StatementStorage(Protocol):
    """Content-addressed read/write access to raw uploaded statement bytes."""

    async def put(self, key: str, data: bytes) -> None:
        """Persist ``data`` under ``key`` (overwriting any existing object)."""
        ...

    async def get(self, key: str) -> bytes:
        """Return the bytes stored under ``key``.

        Raises :class:`StatementStorageError` when the object is missing, so a
        re-processing attempt fails loudly instead of silently importing nothing.
        """
        ...
