"""Menu and margin API (FR-MNU-02/03/06/07): items with current cost and GP, cost timeline with drivers,
and the repricing what-if (prices are never changed automatically)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import site_context
from app.core.errors import NotFound, Unprocessable
from app.core.security import Role
from app.core.tenancy.context import SiteContext
from app.domain.intelligence.models import ItemCostSnapshot
from app.domain.inventory.models import Ingredient
from app.domain.menu.margin_engine import cost_at
from app.domain.menu.models import MenuItem
from app.domain.menu.repricing import suggest
from app.domain.pricing.attribution import item_attribution

router = APIRouter(prefix="/menu", tags=["menu"])
GM = Annotated[SiteContext, Depends(site_context(Role.general_manager))]


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    category: str
    price_ex_vat_minor: int | None = None
    cost_minor: int | None = None
    gp_pct: Decimal | None = None
    cm_minor: int | None = None
    units_28d: Decimal | None = None


class CostPoint(BaseModel):
    business_date: date
    cost_minor: int
    price_ex_vat_minor: int
    gp_pct: Decimal
    cm_minor: int
    units_sold: Decimal
    cost_breakdown: dict[str, int]


class DriverOut(BaseModel):
    ingredient_id: uuid.UUID
    ingredient_name: str
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    cost_from_minor: int
    cost_to_minor: int
    delta_minor: int
    pct_of_change: Decimal


class AttributionOut(BaseModel):
    date_from: date
    date_to: date
    cost_from_minor: int
    cost_to_minor: int
    gp_from_pct: Decimal
    gp_to_pct: Decimal
    drivers: list[DriverOut]


class WhatIfIn(BaseModel):
    price_gross_minor: int | None = Field(None, gt=0, description="Evaluate this price; omit for the suggestion")
    target_gp_pct: Decimal | None = Field(None, gt=0, lt=100)


class WhatIfOut(BaseModel):
    cost_minor: int
    current_gross_minor: int
    suggested_gross_minor: int
    current_gp_pct: Decimal
    suggested_gp_pct: Decimal
    target_gp_pct: Decimal
    weekly_units: Decimal
    weekly_gp_impact_minor: int
    weekly_gp_impact_lower_volume_minor: int


@router.get("/items", response_model=list[MenuItemOut])
async def list_items(ctx: GM):
    items = (await ctx.session.execute(select(MenuItem).where(
        MenuItem.organisation_id == ctx.organisation_id, MenuItem.active.is_(True)).order_by(MenuItem.code))).scalars()
    latest = (await ctx.session.execute(select(func.max(ItemCostSnapshot.business_date)).where(
        ItemCostSnapshot.site_id == ctx.site_id))).scalar()
    snaps = {s.menu_item_id: s for s in (await ctx.session.execute(select(ItemCostSnapshot).where(
        ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.business_date == latest))).scalars()} if latest else {}
    units = dict((await ctx.session.execute(select(ItemCostSnapshot.menu_item_id, func.sum(ItemCostSnapshot.units_sold))
                                            .where(ItemCostSnapshot.site_id == ctx.site_id,
                                                   ItemCostSnapshot.business_date > latest - timedelta(days=28))
                                            .group_by(ItemCostSnapshot.menu_item_id))).all()) if latest else {}
    out = []
    for item in items:
        s = snaps.get(item.id)
        out.append(MenuItemOut.model_validate(item).model_copy(update={
            "cost_minor": s.cost_minor if s else None, "gp_pct": s.gp_pct if s else None,
            "cm_minor": s.cm_minor if s else None, "units_28d": units.get(item.id),
            "price_ex_vat_minor": s.price_ex_vat_minor if s else None}))
    return out


async def _item(ctx: SiteContext, item_id: uuid.UUID) -> MenuItem:
    item = (await ctx.session.execute(select(MenuItem).where(
        MenuItem.id == item_id, MenuItem.organisation_id == ctx.organisation_id))).scalar_one_or_none()
    if item is None:
        raise NotFound("Menu item not found.", code="menu_item_not_found")
    return item


@router.get("/items/{item_id}/cost-timeline", response_model=list[CostPoint])
async def cost_timeline(item_id: uuid.UUID, ctx: GM, from_date: date | None = Query(None, alias="from"),
                        to_date: date | None = Query(None, alias="to")):
    await _item(ctx, item_id)
    q = select(ItemCostSnapshot).where(ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.menu_item_id == item_id)
    if from_date:
        q = q.where(ItemCostSnapshot.business_date >= from_date)
    if to_date:
        q = q.where(ItemCostSnapshot.business_date <= to_date)
    rows = (await ctx.session.execute(q.order_by(ItemCostSnapshot.business_date))).scalars().all()
    names = {str(i): n for i, n in (await ctx.session.execute(select(Ingredient.id, Ingredient.name).where(
        Ingredient.organisation_id == ctx.organisation_id))).all()}
    return [CostPoint(business_date=r.business_date, cost_minor=r.cost_minor, price_ex_vat_minor=r.price_ex_vat_minor,
                      gp_pct=r.gp_pct, cm_minor=r.cm_minor, units_sold=r.units_sold,
                      cost_breakdown={names.get(k, k): v for k, v in r.cost_breakdown.items()}) for r in rows]


@router.get("/items/{item_id}/attribution", response_model=AttributionOut)
async def attribution(item_id: uuid.UUID, ctx: GM, from_date: date = Query(..., alias="from"),
                      to_date: date = Query(..., alias="to")):
    """FR-MNU-07: which ingredient and supplier price changes drove the dish's cost."""
    await _item(ctx, item_id)
    a = await item_attribution(ctx.session, organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                               menu_item_id=item_id, date_from=from_date, date_to=to_date)
    if a is None:
        raise NotFound("No cost snapshots for those dates.", code="snapshot_not_found")
    return AttributionOut(date_from=a.date_from, date_to=a.date_to, cost_from_minor=a.cost_from_minor,
                          cost_to_minor=a.cost_to_minor, gp_from_pct=a.gp_from_pct, gp_to_pct=a.gp_to_pct,
                          drivers=[DriverOut(**d.__dict__) for d in a.drivers])


@router.post("/items/{item_id}/what-if", response_model=WhatIfOut)
async def what_if(item_id: uuid.UUID, ctx: GM, body: WhatIfIn | None = None):
    """FR-MNU-06: the price restoring the target GP %, or a manager's price, with weekly GP impact at current
    volume and at -5% volume."""
    await _item(ctx, item_id)
    body = body or WhatIfIn.model_validate({})
    today = await ctx.today()
    c = await cost_at(ctx, item_id, today)
    if c.price_gross_minor is None or c.vat_rate is None:
        raise Unprocessable("The item has no price at this site.", code="no_price")
    units = (await ctx.session.execute(select(func.coalesce(func.sum(ItemCostSnapshot.units_sold), 0)).where(
        ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.menu_item_id == item_id,
        ItemCostSnapshot.business_date.between(today - timedelta(days=27), today)))).scalar() or 0
    target = (body.target_gp_pct / 100) if body.target_gp_pct else Decimal(str(ctx.config.get("targets.gp_pct")))
    r = suggest(cost_minor=c.cost_minor, current_gross_minor=c.price_gross_minor, vat_rate=c.vat_rate, target_gp=target,
                endings=ctx.config.get("menu.price_endings"), weekly_units=Decimal(units) / 4,
                gross_override=body.price_gross_minor)
    return WhatIfOut(cost_minor=c.cost_minor, **r.__dict__)
