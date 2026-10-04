"""Schedule runs: each scheduled job is enqueued once per site and local date (FR-JOB-05)."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk
from app.core.tenancy.scoping import OrgScoped

SCHEDULED_JOBS = ("nightly.pipeline", "outcomes.evaluate", "brief.daily", "brief.weekly", "followups.run")


class ScheduleRun(UUIDPk, OrgScoped, Base):
    __tablename__ = "schedule_run"
    __table_args__ = (Index("uq_schedule_run", "site_id", "job", "local_date", unique=True),)

    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"))
    job: Mapped[str] = mapped_column(String(60))
    local_date: Mapped[date] = mapped_column(Date)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    job_id: Mapped[int | None]


# --------------------------------------------------------------------------------------------------
# Dispatcher (called every 5 minutes by Cloud Scheduler; GitHub Actions cron as fallback)
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Due:
    organisation_id: uuid.UUID
    site_id: uuid.UUID
    job: str
    local_date: date
    business_date: date


SCHEDULE_FIELD = {"nightly.pipeline": "nightly_pipeline", "outcomes.evaluate": "outcome_evaluation",
                  "followups.run": "follow_ups", "brief.daily": "daily_brief", "brief.weekly": "weekly_recap"}
PREVIOUS_DAY_JOBS = ("nightly.pipeline", "brief.daily", "brief.weekly")


def due_jobs(now_utc: datetime, sites: list[tuple[uuid.UUID, uuid.UUID, str, Any]]) -> list[Due]:
    """Jobs whose local scheduled time has passed today, per site timezone. The nightly pipeline processes
    the previous business date, as do the briefs; outcomes and follow-ups run for today."""
    out = []
    for org_id, site_id, tz, schedules in sites:
        local = now_utc.astimezone(ZoneInfo(tz))
        for job, field_name in SCHEDULE_FIELD.items():
            at: time = getattr(schedules, field_name)
            if local.time() < at or (job == "brief.weekly" and local.weekday() != schedules.weekly_recap_weekday):
                continue
            business = local.date() - timedelta(days=1) if job in PREVIOUS_DAY_JOBS else local.date()
            out.append(Due(org_id, site_id, job, local.date(), business))
    return out


async def dispatch(session: AsyncSession, now_utc: datetime, *, include_simulated: bool = False) -> list[dict[str, Any]]:
    """Enqueue each due job once per site, job and local date (ScheduleRun is the unique key).
    Sites on the simulator clock are advanced by `simulator.next_day`, which enqueues the same jobs."""
    from app.core.jobs import enqueue, job_key
    from app.core.tenancy.config import resolve_config
    from app.core.tenancy.models import Site

    sites = []
    for site in (await session.execute(select(Site))).scalars():
        cfg = await resolve_config(session, site.organisation_id, site.id)
        if cfg.get("simulation.enabled") and not include_simulated:
            continue
        sites.append((site.organisation_id, site.id, site.timezone, cfg.get("site.schedules")))
    queued = []
    for d in due_jobs(now_utc, sites):
        run_id = (await session.execute(insert(ScheduleRun).values(
            id=uuid.uuid4(), organisation_id=d.organisation_id, site_id=d.site_id, job=d.job, local_date=d.local_date,
        ).on_conflict_do_nothing(index_elements=["site_id", "job", "local_date"]).returning(ScheduleRun.id))
                  ).scalar_one_or_none()
        if run_id is None:
            continue
        job_id = await enqueue(session, d.job, key=job_key(d.job, d.site_id, d.business_date.isoformat()),
                               lock=f"site:{d.site_id}",
                               args={"organisation_id": str(d.organisation_id), "site_id": str(d.site_id),
                                     "business_date": d.business_date.isoformat()})
        await session.execute(update(ScheduleRun).where(ScheduleRun.id == run_id).values(job_id=job_id))
        queued.append({"site_id": str(d.site_id), "job": d.job, "business_date": d.business_date.isoformat(),
                       "job_id": job_id})
    return queued
