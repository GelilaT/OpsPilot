"""Anomaly detection API (FR-ANO): list with filters; dismiss as expected (suppresses 7 days, FR-ANO-06)."""

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import site_context
from app.core.audit import record_audit
from app.core.errors import NotFound
from app.core.security import Role
from app.core.tenancy.context import SiteContext
from app.domain.intelligence.models import Anomaly

router = APIRouter(prefix="/anomalies", tags=["anomalies"])
Reader = Annotated[SiteContext, Depends(site_context(Role.shift_manager))]
GM = Annotated[SiteContext, Depends(site_context(Role.general_manager))]


class AnomalyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    detector: str
    subject: dict[str, Any]
    period_start: date
    period_end: date
    severity: str
    status: str
    facts: dict[str, Any]
    weekly_impact_minor: int
    streak: int
    parent_id: uuid.UUID | None
    dismissed_until: date | None
    created_at: datetime


class DismissIn(BaseModel):
    reason: str = Field(min_length=3, max_length=400)


@router.get("", response_model=list[AnomalyOut])
async def list_anomalies(ctx: Reader, severity: str | None = None, detector: str | None = None,
                         status: str | None = None, since: date | None = None, limit: int = Query(50, le=200)):
    q = select(Anomaly).where(Anomaly.site_id == ctx.site_id)
    if severity:
        q = q.where(Anomaly.severity.in_(severity.split(",")))
    if detector:
        q = q.where(Anomaly.detector.in_(detector.split(",")))
    if status:
        q = q.where(Anomaly.status.in_(status.split(",")))
    if since:
        q = q.where(Anomaly.period_end >= since)
    return list((await ctx.session.execute(q.order_by(Anomaly.period_end.desc(), Anomaly.weekly_impact_minor.desc())
                                           .limit(limit))).scalars().all())


@router.post("/{anomaly_id}/dismiss", response_model=AnomalyOut)
async def dismiss(anomaly_id: uuid.UUID, body: DismissIn, ctx: GM):
    a = (await ctx.session.execute(select(Anomaly).where(
        Anomaly.id == anomaly_id, Anomaly.site_id == ctx.site_id).with_for_update())).scalar_one_or_none()
    if a is None:
        raise NotFound("Anomaly not found.", code="anomaly_not_found")
    before = {"status": a.status}
    a.status = "dismissed"
    until = (await ctx.today()) + timedelta(days=ctx.config.get("detection.dismiss_suppress_days"))
    a.dismissed_until = until
    record_audit(ctx.session, actor=ctx.actor, entity_type="anomaly", entity_id=a.id, action="dismiss",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id, before=before,
                 after={"status": "dismissed", "until": until.isoformat(), "reason": body.reason})
    await ctx.session.flush()
    return a
