"""StoragePort on local disk (development). Files are private; reads go through short-lived HMAC-signed
URLs served by GET /files/{key} with a no-sniff, sandboxed response (never rendered as HTML)."""

import asyncio
import os
from pathlib import Path

from app.core.signing import sign_file_url
from app.ports.errors import PermanentError

PROVIDER = "local"


class LocalStorage:
    provider = PROVIDER

    def __init__(self, root: str | Path, *, public_base_url: str, signing_secret: str) -> None:
        self.root = Path(root).resolve()
        self.public_base_url = public_base_url
        self.signing_secret = signing_secret

    def path_for(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise PermanentError(f"Invalid storage key {key!r}", provider=PROVIDER)
        return path

    async def put(self, data: bytes, *, key: str, content_type: str) -> str:
        path = self.path_for(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                return  # content-addressed keys are never overwritten
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)

        await asyncio.to_thread(write)
        return key

    async def get(self, key: str) -> bytes:
        path = self.path_for(key)
        if not path.exists():
            raise PermanentError(f"No object {key!r}", provider=PROVIDER)
        return await asyncio.to_thread(path.read_bytes)

    async def exists(self, key: str) -> bool:
        return self.path_for(key).exists()

    async def signed_url(self, key: str, *, ttl_seconds: int = 600, content_type: str | None = None) -> str:
        return sign_file_url(self.public_base_url, self.signing_secret, key, ttl_seconds,
                             content_type or "application/octet-stream")
