"""Morning Dashboard (SCR-02) and catalogue lookups.

KPI cards compare the latest business day with the same weekday over the baseline weeks (median), as the
detectors do: currency and count deltas in %, ratio deltas in percentage points (v1 FR rule).
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import site_context
from app.core.errors import Unprocessable
from app.core.security import Role
from app.core.tenancy.context import SiteContext
from app.domain.actions.models import Recommendation, RecommendationOutcome
from app.domain.detectors.baseline import same_weekdays
from app.domain.detectors.data import load_days
from app.domain.detectors.kpis import Kpi, compute_kpis
from app.domain.intelligence.models import Anomaly
from app.domain.inventory.models import Ingredient, SiteIngredient
from app.domain.purchasing.invoice_models import InvoiceDocument
from app.domain.purchasing.models import Supplier, SupplierProduct
from app.domain.sales.models import SalesOrder

router = APIRouter(tags=["dashboard"])
Reader = Annotated[SiteContext, Depends(site_context(Role.shift_manager))]

REVIEW_STATES = ("needs_review", "ready_for_approval", "failed")


class RiskOut(BaseModel):
    anomaly_id: uuid.UUID
    detector: str
    subject: dict[str, Any]
    severity: str
    weekly_impact_minor: int
    period_end: date
    status: str


class OutcomeBrief(BaseModel):
    recommendation_id: uuid.UUID
    title: str
    metric: str
    verdict: str
    effect_pct: Decimal | None
    measured_at: datetime


class DashboardOut(BaseModel):
    business_date: date  # the day shown (the latest business day unless `as_of` was given)
    latest_date: date
    earliest_date: date | None
    kpis: list[Kpi]
    pending_approvals: int
    pending_impact_minor: int
    invoices_to_review: dict[str, int]
    risks: list[RiskOut]
    outcomes: list[OutcomeBrief]


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(ctx: Reader, as_of: date | None = None):
    """KPIs, risks and outcomes for `as_of` (default: the latest business day). Work queues are always live."""
    latest = await ctx.today()
    earliest = (await ctx.session.execute(select(func.min(SalesOrder.business_date)).where(
        SalesOrder.site_id == ctx.site_id))).scalar_one_or_none()
    day = as_of or latest
    if day > latest:
        raise Unprocessable("as_of cannot be after the latest business day.")
    if earliest is not None and day < earliest:
        raise Unprocessable("as_of is before the first day with data.")
    base_days = same_weekdays(day, ctx.config.get("detection.baseline_weeks"))
    days = await load_days(ctx.session, ctx.site_id, [day, *base_days])
    pending = (await ctx.session.execute(select(func.count(), func.coalesce(func.sum(
        Recommendation.expected_impact_minor), 0)).where(
        Recommendation.site_id == ctx.site_id, Recommendation.status == "proposed"))).one()
    counts = dict((await ctx.session.execute(select(InvoiceDocument.state, func.count()).where(
        InvoiceDocument.site_id == ctx.site_id, InvoiceDocument.state.in_(REVIEW_STATES)).group_by(
        InvoiceDocument.state))).all())
    risks = (await ctx.session.execute(select(Anomaly).where(
        Anomaly.site_id == ctx.site_id, Anomaly.parent_id.is_(None), Anomaly.status.in_(("open", "investigating")),
        Anomaly.period_end >= day - timedelta(days=7), Anomaly.period_end <= day).order_by(
        Anomaly.weekly_impact_minor.desc()).limit(8))).scalars().all()
    outcome_q = select(RecommendationOutcome, Recommendation).join(
        Recommendation, Recommendation.id == RecommendationOutcome.recommendation_id).where(
        RecommendationOutcome.site_id == ctx.site_id)
    if day < latest:
        outcome_q = outcome_q.where(RecommendationOutcome.created_at < ctx.day_bounds_utc(day)[1])
    outcomes = (await ctx.session.execute(outcome_q.order_by(
        RecommendationOutcome.created_at.desc()).limit(5))).all()
    return DashboardOut(
        business_date=day, latest_date=latest, earliest_date=earliest,
        kpis=compute_kpis(days[day], [days[d] for d in base_days]),
        pending_approvals=int(pending[0]), pending_impact_minor=int(pending[1]), invoices_to_review=counts,
        risks=[RiskOut(anomaly_id=a.id, detector=a.detector, subject=a.subject, severity=a.severity,
                       weekly_impact_minor=a.weekly_impact_minor, period_end=a.period_end, status=a.status)
               for a in risks],
        outcomes=[OutcomeBrief(recommendation_id=r.id, title=r.parameters.get("title", r.type), metric=o.metric,
                               verdict=o.verdict, effect_pct=o.effect_pct, measured_at=o.created_at)
                  for o, r in outcomes])


class IngredientOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    category: str
    base_unit: str
    default_supplier_id: uuid.UUID | None
    default_supplier_name: str | None
    suppliers: int


@router.get("/ingredients", response_model=list[IngredientOut])
async def ingredients(ctx: Reader):
    """Ingredient catalogue with the site's default supplier and how many suppliers offer each."""
    defaults = {i: (s, n) for i, s, n in (await ctx.session.execute(select(
        SiteIngredient.ingredient_id, Supplier.id, Supplier.name).join(
        SupplierProduct, SupplierProduct.id == SiteIngredient.default_supplier_product_id).join(
        Supplier, Supplier.id == SupplierProduct.supplier_id).where(SiteIngredient.site_id == ctx.site_id))).all()}
    offered = dict((await ctx.session.execute(select(
        SupplierProduct.ingredient_id, func.count(func.distinct(SupplierProduct.supplier_id))).where(
        SupplierProduct.organisation_id == ctx.organisation_id, SupplierProduct.active.is_(True)).group_by(
        SupplierProduct.ingredient_id))).all())
    rows = (await ctx.session.execute(select(Ingredient).where(
        Ingredient.organisation_id == ctx.organisation_id, Ingredient.active.is_(True)).order_by(
        Ingredient.name))).scalars().all()
    return [IngredientOut(id=i.id, code=i.code, name=i.name, category=i.category, base_unit=i.base_unit,
                          default_supplier_id=defaults.get(i.id, (None, None))[0],
                          default_supplier_name=defaults.get(i.id, (None, None))[1], suppliers=int(offered.get(i.id, 0)))
            for i in rows]
