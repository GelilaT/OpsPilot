"""PostgreSQL-backed token bucket shared by all worker instances (FR-JOB-07, PR-06).

AI jobs call `try_acquire`; when no token is available they defer themselves by the returned
number of seconds instead of failing or consuming a retry attempt.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, String, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RateBucket(Base):
    __tablename__ = "rate_bucket"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    tokens: Mapped[float] = mapped_column(Float)
    capacity: Mapped[float] = mapped_column(Float)
    refill_per_second: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def try_acquire(session: AsyncSession, name: str, *, capacity: float, per_seconds: float,
                      cost: float = 1.0) -> float:
    """Take `cost` tokens. Returns 0 on success, else the seconds to wait before retrying."""
    refill = capacity / per_seconds
    await session.execute(
        insert(RateBucket)
        .values(name=name, tokens=capacity, capacity=capacity, refill_per_second=refill)
        .on_conflict_do_nothing()
    )
    bucket = (await session.execute(
        select(RateBucket).where(RateBucket.name == name).with_for_update()
    )).scalar_one()
    now = (await session.execute(select(func.now()))).scalar_one()
    elapsed = max(0.0, (now - bucket.updated_at).total_seconds())
    bucket.capacity, bucket.refill_per_second = capacity, refill
    tokens = min(capacity, bucket.tokens + elapsed * refill)
    bucket.updated_at = now
    if tokens >= cost:
        bucket.tokens = tokens - cost
        return 0.0
    bucket.tokens = tokens
    return (cost - tokens) / refill


async def acquire_ai_slot(session: AsyncSession, *, per_minute: int, per_day: int) -> float:
    """Both the per-minute and the daily Gemini budget must allow the call."""
    wait = await try_acquire(session, "ai:minute", capacity=per_minute, per_seconds=60)
    if wait:
        return wait
    wait = await try_acquire(session, "ai:day", capacity=per_day, per_seconds=86400)
    if wait:  # give the minute token back
        await try_acquire(session, "ai:minute", capacity=per_minute, per_seconds=60, cost=-1)
    return wait
