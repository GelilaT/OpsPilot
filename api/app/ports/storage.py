"""StoragePort: private object storage for invoice originals (SRS 2.3)."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class StoragePort(Protocol):
    provider: str

    async def put(self, data: bytes, *, key: str, content_type: str) -> str:
        """Store bytes under `key` (never overwritten if present) and return the key."""
        ...

    async def get(self, key: str) -> bytes: ...

    async def signed_url(self, key: str, *, ttl_seconds: int = 600, content_type: str | None = None) -> str:
        """Short-lived read URL (10 minutes by default)."""
        ...

    async def exists(self, key: str) -> bool: ...
