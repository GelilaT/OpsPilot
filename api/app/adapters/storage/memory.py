"""In-memory StoragePort fake (FR-INT-04)."""

from app.ports.errors import PermanentError

PROVIDER = "memory"


class MemoryStorage:
    provider = PROVIDER

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, data: bytes, *, key: str, content_type: str) -> str:
        self.objects.setdefault(key, (data, content_type))
        return key

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise PermanentError(f"No object {key!r}", provider=PROVIDER)
        return self.objects[key][0]

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def signed_url(self, key: str, *, ttl_seconds: int = 600, content_type: str | None = None) -> str:
        return f"memory://{key}?ttl={ttl_seconds}&ct={content_type or ''}"
