"""Object storage behind one interface (R-1.2).

The rest of the application never learns which cloud it is on. Adding S3 is a new
subclass and a line in `get_storage`; nothing else changes.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
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


class AzureBlobStorage(Storage):
    """Production today. Container stays private; only this class holds the
    credential and it never leaves the server (R-4.2, R-5.5)."""

    def __init__(self, connection_string: str, container: str):
        from azure.storage.blob import ContainerClient
        self._c = ContainerClient.from_connection_string(connection_string, container)

    def list(self, prefix: str):
        return sorted(b.name for b in self._c.list_blobs(name_starts_with=prefix))

    def get(self, path: str) -> bytes:
        return self._c.get_blob_client(path).download_blob().readall()

    def exists(self, path: str) -> bool:
        return self._c.get_blob_client(path).exists()


# class S3Storage(Storage): ...   <- the whole cost of moving to AWS


def get_storage() -> Storage:
    from app.core.config import settings
    s = settings()
    # LEGACY-V1-BEGIN
    if s.storage_backend == "v1_public":
        from app.services.legacy_v1 import PublicHttpStorage
        return PublicHttpStorage(s.v1_base_url)
    # LEGACY-V1-END
    if s.storage_backend == "local":
        return LocalStorage(s.local_storage_root)
    if s.storage_backend == "azure":
        return AzureBlobStorage(s.azure_connection_string, s.azure_container)
    raise RuntimeError(f"unknown storage backend: {s.storage_backend}")
