"""Abstract storage backend."""
from __future__ import annotations

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Abstract interface for file storage backends."""

    @abstractmethod
    async def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Upload file data and return the storage URL/path."""
        ...

    @abstractmethod
    async def download(self, key: str) -> bytes:
        """Download and return file bytes."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete file. Returns True if deleted, False if not found."""
        ...

    @abstractmethod
    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a presigned URL for direct access."""
        ...

    @abstractmethod
    async def list_keys(self, prefix: str = "") -> list[str]:
        """List all keys with optional prefix filter."""
        ...
