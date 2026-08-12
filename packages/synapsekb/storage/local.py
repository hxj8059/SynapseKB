from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles


class LocalObjectStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if key.startswith("/") or ".." in Path(key).parts:
            raise ValueError("Unsafe object key")
        resolved = (self.root / key).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("Object key escapes storage root")
        return resolved

    async def put_file(self, key: str, path: Path, content_type: str) -> None:
        del content_type
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "rb") as source, aiofiles.open(target, "wb") as output:
            while chunk := await source.read(1024 * 1024):
                await output.write(chunk)

    async def read(self, key: str) -> bytes:
        async with aiofiles.open(self._path(key), "rb") as handle:
            return await handle.read()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    async def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    async def iter_bytes(self, key: str) -> AsyncIterator[bytes]:
        async with aiofiles.open(self._path(key), "rb") as handle:
            while chunk := await handle.read(1024 * 1024):
                yield chunk

    async def presign_upload(self, key: str, content_type: str, expires_seconds: int = 900) -> None:
        del key, content_type, expires_seconds
        return None

    async def presign_download(self, key: str, expires_seconds: int = 300) -> None:
        del key, expires_seconds
        return None
