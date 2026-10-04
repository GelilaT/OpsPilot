"""Procurement intelligence API (FR-PRC-03/04/10): supplier comparison and cost increase attribution."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import site_context
from app.core.security import Role
from app.core.tenancy.context import SiteContext
from app.domain.inventory.models import SiteIngredient
from app.domain.pricing.attribution import attribute_period
from app.domain.pricing.supplier_ranking import rank_for_ingredient, switch_candidate
from app.domain.purchasing.models import SupplierProduct

router = APIRouter(prefix="/procurement", tags=["procurement"])
GM = Annotated[SiteContext, Depends(site_context(Role.general_manager))]


class SupplierOfferOut(BaseModel):
    rank: int
    supplier_id: uuid.UUID
    supplier_name: str
    supplier_product_id: uuid.UUID
    product_name: str
    price_per_base_minor: Decimal | None
    price_observed_on: date | None
    fill_rate: Decimal | None
    lead_time_days: int
    is_default: bool = False


class ComparisonOut(BaseModel):
    ingredient_id: uuid.UUID
    offers: list[SupplierOfferOut]
    switch_to: uuid.UUID | None
    switch_saving_pct: Decimal | None


class AttributionRowOut(BaseModel):
    ingredient_id: uuid.UUID
    ingredient_name: str
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    previous_price_per_base_minor: Decimal
    current_price_per_base_minor: Decimal
    current_qty_base: Decimal
    delta_cost_minor: int
    pct_of_total: Decimal


class SupplierAttributionOut(BaseModel):
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    delta_cost_minor: int
    pct_of_total: Decimal


class AttributionOut(BaseModel):
    current_start: date
    current_end: date
    prior_start: date
    prior_end: date
    total_delta_minor: int
    ingredients: list[AttributionRowOut]
    suppliers: list[SupplierAttributionOut]


@router.get("/comparison", response_model=ComparisonOut)
async def comparison(ctx: GM, ingredient_id: uuid.UUID = Query(...), as_of: date | None = None):
    day = as_of or await ctx.today()
    offers = await rank_for_ingredient(ctx.session, ctx.organisation_id, ctx.site_id, ingredient_id, as_of=day)
    default = (await ctx.session.execute(select(SupplierProduct.supplier_id).join(
        SiteIngredient, SiteIngredient.default_supplier_product_id == SupplierProduct.id).where(
        SiteIngredient.site_id == ctx.site_id, SiteIngredient.ingredient_id == ingredient_id))).scalar_one_or_none()
    cand = switch_candidate(offers, default, min_saving_pct=Decimal(str(ctx.config.get("procurement.switch_min_saving_pct"))),
                            min_fill_rate=Decimal(str(ctx.config.get("procurement.switch_min_fill_rate")))) \
        if default else None
    return ComparisonOut(ingredient_id=ingredient_id, offers=[SupplierOfferOut(
        **o.__dict__, is_default=o.supplier_id == default) for o in offers],
        switch_to=cand.alternative.supplier_id if cand else None, switch_saving_pct=cand.saving_pct if cand else None)


@router.get("/cost-attribution", response_model=AttributionOut)
async def cost_attribution(ctx: GM, from_date: date = Query(..., alias="from"), to_date: date = Query(..., alias="to")):
    a = await attribute_period(ctx.session, organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                               current_start=from_date, current_end=to_date)
    return AttributionOut(current_start=a.current_start, current_end=a.current_end, prior_start=a.prior_start,
                          prior_end=a.prior_end, total_delta_minor=a.total_delta_minor,
                          ingredients=[AttributionRowOut(**r.__dict__) for r in a.ingredients],
                          suppliers=[SupplierAttributionOut(**s.__dict__) for s in a.suppliers])
