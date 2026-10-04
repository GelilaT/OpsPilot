"""Transactional job enqueue (FR-JOB-01/02) and the pollable JobRun resource (FR-API-07).

Jobs are inserted into Procrastinate's queue with the same SQLAlchemy transaction as the state
change that requires them, so either both commit or neither does. Each job carries a queueing lock
`task:entity:version`; a second enqueue of the same key while one is pending is a no-op.
"""

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.tenancy.scoping import OrgScoped

JOB_RUN_STATES = ("queued", "running", "succeeded", "failed", "deferred")


class JobRun(UUIDPk, Timestamps, OrgScoped, Base):
    """Pollable status of a long-running operation started through the API."""

    __tablename__ = "job_run"
    __table_args__ = (Index("ix_job_run_org_created", "organisation_id", "created_at"),)

    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"))
    task: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(2000))
    requested_by: Mapped[str] = mapped_column(String(120))
    procrastinate_job_id: Mapped[int | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def job_key(task: str, entity: Any, version: Any = 0) -> str:
    """Idempotency key for a job: (task, entity, version) - FR-JOB-02."""
    return f"{task}:{entity}:{version}"


async def enqueue(
    session: AsyncSession,
    task: str,
    *,
    args: dict[str, Any],
    key: str,
    queue: str = "default",
    priority: int = 0,
    scheduled_at: datetime | None = None,
    lock: str | None = None,
) -> int | None:
    """Insert a Procrastinate job inside the caller's transaction.

    Returns the job id, or None when an identical job (same `key`) is already waiting.
    `lock` serialises jobs that touch the same entity (e.g. one invoice document).
    """
    stmt = text(
        "SELECT unnest(procrastinate_defer_jobs_v1(ARRAY[ROW("
        ":queue, :task, :priority, :lock, :qlock, CAST(:args AS jsonb), :scheduled_at"
        ")::procrastinate_job_to_defer_v1]))"
    )
    params = {
        "queue": queue,
        "task": task,
        "priority": priority,
        "lock": lock,
        "qlock": key,
        "args": json.dumps(args, default=str),
        "scheduled_at": scheduled_at,
    }
    try:
        async with session.begin_nested():
            return (await session.execute(stmt, params)).scalar_one()
    except IntegrityError as exc:
        if "procrastinate_jobs_queueing_lock_idx" in str(exc.orig):
            return None
        raise


async def mark_run(session: AsyncSession, run_id: uuid.UUID, status: str, **fields: Any) -> None:
    run = await session.get(JobRun, run_id, with_for_update=True)
    if run is None:
        return
    run.status = status
    if status == "running":
        run.started_at = func.now()
        run.attempts = (run.attempts or 0) + 1
    if status in ("succeeded", "failed"):
        run.finished_at = func.now()
    for k, v in fields.items():
        setattr(run, k, v)
