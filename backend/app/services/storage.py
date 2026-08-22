"""Object storage behind one interface (R-1.2).

The rest of the application never learns which cloud it is on. Adding S3 is a new
subclass and a line in `get_storage`; nothing else changes.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import Iterable


class Storage(ABC):
    @abstractmethod
    def list(self, prefix: str) -> Iterable[str]:
        """Blob names under a prefix. Names only; cheap. This is what makes
        date-partitioned event paths a query (R-5.2)."""

    @abstractmethod
    def get(self, path: str) -> bytes: ...

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def put(self, path: str, data: bytes, content_type: str = "application/json") -> None:
        """Overwrite a blob.

        This interface was read-only until 2026-08-22 and that was deliberate.
        It gained a write for exactly one caller: publishing the signed device
        configuration to `sites/{site_id}/remote_config.json`, which the data
        contract makes storage-transported rather than an HTTP endpoint (D-020).

        The rule it does **not** relax: the browser still never writes to
        storage, and no write-capable credential goes anywhere near the client.
        This runs server-side, behind an admin session.
        """


class LocalStorage(Storage):
    """Development. Reads the fixture tree. No cloud account (R-9.4)."""

    def __init__(self, root: str):
        self.root = Path(root)

    def list(self, prefix: str):
        base = self.root / prefix
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())

    def get(self, path: str) -> bytes:
        return (self.root / path).read_bytes()

    def exists(self, path: str) -> bool:
        return (self.root / path).is_file()

    def put(self, path: str, data: bytes, content_type: str = "application/json") -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a device polling this blob must never read a half
        # written document and fail its signature check over a torn file.
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)


class AzureBlobStorage(Storage):
    """Production today. Container stays private; only this class holds the
    credential and it never leaves the server (R-4.2, R-5.5).

    Constructed once per process, not per request — see `get_storage`. Building
    a `ContainerClient` sets up an HTTP pipeline and parses the credential, and
    doing that on every request is invisible against `LocalStorage` and
    expensive against a real account.
    """

    # A blob read that never returns must not hold a request open forever. These
    # bound the socket, not the whole download; a large clip still streams.
    CONNECT_TIMEOUT_S = 10
    READ_TIMEOUT_S = 60

    def __init__(self, connection_string: str, container: str):
        from azure.storage.blob import ContainerClient
        self._c = ContainerClient.from_connection_string(
            connection_string, container,
            connection_timeout=self.CONNECT_TIMEOUT_S,
            read_timeout=self.READ_TIMEOUT_S,
        )

    def list(self, prefix: str):
        return sorted(b.name for b in self._c.list_blobs(name_starts_with=prefix))

    def get(self, path: str) -> bytes:
        return self._c.get_blob_client(path).download_blob().readall()

    def exists(self, path: str) -> bool:
        return self._c.get_blob_client(path).exists()

    def put(self, path: str, data: bytes, content_type: str = "application/json") -> None:
        from azure.storage.blob import ContentSettings
        # Blob PUT is atomic: a reader sees the old blob or the new one, never a
        # partial write, so no temp-and-rename dance is needed here.
        self._c.get_blob_client(path).upload_blob(
            data, overwrite=True,
            content_settings=ContentSettings(content_type=content_type))


# class S3Storage(Storage): ...   <- the whole cost of moving to AWS


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    """One instance per process.

    Cached deliberately: this is called on every data request, and the Azure
    client is expensive to build. `settings()` is cached the same way, so the
    backend is already a restart-to-reconfigure service. Tests that switch
    backends mid-process call `get_storage.cache_clear()`.
    """
    from app.core.config import settings
    s = settings()
    if s.storage_backend == "local":
        return LocalStorage(s.local_storage_root)
    if s.storage_backend == "azure":
        return AzureBlobStorage(s.azure_connection_string, s.azure_container)
    raise RuntimeError(f"unknown storage backend: {s.storage_backend}")
