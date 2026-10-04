from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import get_sessionmaker

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready() -> dict:
    async with get_sessionmaker()() as s:
        await s.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
