"""Local filesystem storage backend for development."""
from __future__ import annotations

from pathlib import Path

import aiofiles
import aiofiles.os

from app.config import settings
from app.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    def __init__(self) -> None:
        self.base_path = Path(settings.storage_local_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        file_path = self.base_path / key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(data)
        return str(file_path)

    async def download(self, key: str) -> bytes:
        file_path = self.base_path / key
        async with aiofiles.open(file_path, "rb") as f:
            return await f.read()

    async def delete(self, key: str) -> bool:
        file_path = self.base_path / key
        try:
            await aiofiles.os.remove(file_path)
            return True
        except FileNotFoundError:
            return False

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        # For local development, return the file path as URL
        return f"file://{self.base_path / key}"

    async def list_keys(self, prefix: str = "") -> list[str]:
        keys: list[str] = []
        for path in self.base_path.rglob("*"):
            if path.is_file():
                relative = str(path.relative_to(self.base_path))
                if relative.startswith(prefix):
                    keys.append(relative)
        return keys
