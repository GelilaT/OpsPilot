"""Serves private files from the local storage adapter through short-lived signed URLs (SRS 2.3).

Responses are never rendered as HTML: the stored content type is pinned, sniffing is disabled and a
sandboxing CSP is applied.
"""

import asyncio
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.core.errors import NotFound
from app.core.settings import get_settings
from app.core.signing import verify_file_signature

router = APIRouter(tags=["files"], include_in_schema=False)
SAFE_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
              "text/csv", "text/plain"}


@router.get("/files/{key:path}")
async def get_file(key: str, exp: int, ct: str, sig: str) -> FileResponse:
    settings = get_settings()
    if not verify_file_signature(settings.storage_signing_secret, key, exp, ct, sig):
        raise NotFound("This link has expired or is invalid.", code="link_expired")

    def locate() -> Path | None:
        root = Path(settings.storage_local_dir)
        root = (root if root.is_absolute() else Path(__file__).resolve().parents[3] / root).resolve()
        path = (root / key).resolve()
        return path if root in path.parents and path.is_file() else None

    path = await asyncio.to_thread(locate)
    if path is None:
        raise NotFound("File not found.")
    media_type = ct if ct in SAFE_TYPES else "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, max-age=60",
        "Content-Disposition": "inline",
    })
