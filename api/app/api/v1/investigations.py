"""Root-cause investigation API (FR-RCA): evidence chain, ranked causes, similar cases; versions; re-run."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import site_context
from app.core.errors import NotFound
from app.core.security import Role
from app.core.tenancy.context import SiteContext
from app.domain.intelligence.models import Anomaly, Investigation
from app.domain.investigation.engine import investigate

router = APIRouter(prefix="/investigations", tags=["investigations"])
Reader = Annotated[SiteContext, Depends(site_context(Role.shift_manager))]
GM = Annotated[SiteContext, Depends(site_context(Role.general_manager))]


class InvestigationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    anomaly_id: uuid.UUID
    version: int
    finding: str
    graph: dict[str, Any]
    confidence: Decimal
    narrative: dict[str, Any]
    draft_recommendations: list[Any]
    status: str
    completed_at: datetime | None
    created_at: datetime


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version: int
    confidence: Decimal
    finding: str
    created_at: datetime


@router.get("", response_model=list[VersionOut])
async def versions(ctx: Reader, anomaly_id: uuid.UUID):
    rows = (await ctx.session.execute(select(Investigation).where(
        Investigation.site_id == ctx.site_id, Investigation.anomaly_id == anomaly_id).order_by(
        Investigation.version.desc()))).scalars().all()
    return list(rows)


@router.get("/{investigation_id}", response_model=InvestigationOut)
async def get_investigation(investigation_id: uuid.UUID, ctx: Reader):
    row = (await ctx.session.execute(select(Investigation).where(
        Investigation.id == investigation_id, Investigation.site_id == ctx.site_id))).scalar_one_or_none()
    if row is None:
        raise NotFound("Investigation not found.", code="investigation_not_found")
    return row


@router.post("/rerun/{anomaly_id}", response_model=InvestigationOut, status_code=status.HTTP_201_CREATED)
async def rerun(anomaly_id: uuid.UUID, ctx: GM):
    """Re-run with the data now available (a late invoice); earlier versions are kept (FR-RCA-08)."""
    anomaly = (await ctx.session.execute(select(Anomaly).where(
        Anomaly.id == anomaly_id, Anomaly.site_id == ctx.site_id))).scalar_one_or_none()
    if anomaly is None:
        raise NotFound("Anomaly not found.", code="anomaly_not_found")
    inv = await investigate(ctx, anomaly)
    await ctx.session.flush()
    return inv
