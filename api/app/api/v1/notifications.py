"""Email notifications: on-demand briefs and the delivery log (FR-BRF-05)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import String, cast, or_, select

from app.api.deps import site_context
from app.core.errors import NotFound, Unprocessable
from app.core.security import Role
from app.core.tenancy.context import SiteContext
from app.domain.notifications.briefs import send_daily_brief, send_weekly_recap
from app.domain.notifications.models import EmailDelivery

router = APIRouter(prefix="/notifications", tags=["notifications"])
Manager = Annotated[SiteContext, Depends(site_context(Role.general_manager))]


class SendBriefIn(BaseModel):
    kind: Literal["daily", "weekly"]


class DeliveryOut(BaseModel):
    id: uuid.UUID
    subject: str
    to: list[str]
    status: str
    provider: str | None
    attempts: int
    last_error: str | None
    kind: str | None
    has_html: bool
    created_at: datetime
    sent_at: datetime | None


def _out(d: EmailDelivery) -> DeliveryOut:
    return DeliveryOut(id=d.id, subject=d.subject, to=list(d.to), status=d.status, provider=d.provider,
                       attempts=d.attempts, last_error=d.last_error, kind=d.ref.get("type"),
                       has_html=bool(d.html_body or (d.ref or {}).get("html")),
                       created_at=d.created_at, sent_at=d.sent_at)


@router.post("/briefs/send", response_model=DeliveryOut)
async def send_brief(body: SendBriefIn, ctx: Manager):
    """Queue the morning brief or weekly recap now, for the latest complete trading day (resends every time)."""
    if not ctx.config.get("notifications.recipients"):
        raise Unprocessable("Add at least one address to notifications.recipients first.", code="no_recipients")
    today = await ctx.today()
    day: date = today if ctx.config.get("simulation.enabled") else today - timedelta(days=1)
    suffix = f":manual:{datetime.now(UTC):%Y%m%d%H%M%S}"
    delivery_id = await (send_daily_brief if body.kind == "daily" else send_weekly_recap)(ctx, day, suffix=suffix)
    row = (await ctx.session.execute(select(EmailDelivery).where(EmailDelivery.id == delivery_id))).scalar_one()
    return _out(row)


@router.get("/deliveries", response_model=list[DeliveryOut])
async def deliveries(ctx: Manager, q: str | None = None, limit: int = Query(20, ge=1, le=100)):
    stmt = select(EmailDelivery).where(EmailDelivery.site_id == ctx.site_id)
    if q and (term := q.strip()):
        stmt = stmt.where(or_(
            EmailDelivery.subject.ilike(f"%{term}%"),
            EmailDelivery.status.ilike(f"%{term}%"),
            cast(EmailDelivery.to, String).ilike(f"%{term}%"),
            EmailDelivery.ref["type"].astext.ilike(f"%{term}%"),
        ))
    rows = (await ctx.session.execute(stmt.order_by(EmailDelivery.created_at.desc()).limit(limit))).scalars().all()
    return [_out(r) for r in rows]


@router.get("/deliveries/{delivery_id}/html", response_class=HTMLResponse)
async def delivery_html(delivery_id: uuid.UUID, ctx: Manager):
    """Preview the styled HTML body (same as recipients see in HTML-capable clients)."""
    row = (await ctx.session.execute(select(EmailDelivery).where(
        EmailDelivery.id == delivery_id, EmailDelivery.site_id == ctx.site_id))).scalar_one_or_none()
    if row is None:
        raise NotFound("Delivery not found.", code="not_found")
    html = row.html_body or (row.ref or {}).get("html")
    if not html:
        raise NotFound("This delivery has no HTML body — send a new brief after migrating and restarting the worker.",
                       code="no_html")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
