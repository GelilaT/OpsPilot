"""Supplier and price history API (FR-PRC-01)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import site_context
from app.core.errors import NotFound
from app.core.security import Role
from app.core.tenancy.context import SiteContext
from app.domain.purchasing.models import PriceObservation, Supplier

router = APIRouter(prefix="/suppliers", tags=["suppliers"])
GM = Annotated[SiteContext, Depends(site_context(Role.general_manager))]


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    vat_number: str | None
    lead_time_days: int


class PricePoint(BaseModel):
    observed_on: date
    price_per_base_minor: Decimal
    unit_price_minor: int
    source: str


@router.get("", response_model=list[SupplierOut])
async def list_suppliers(ctx: GM):
    rows = (await ctx.session.execute(select(Supplier).where(
        Supplier.organisation_id == ctx.organisation_id, Supplier.active.is_(True)).order_by(Supplier.name))).scalars()
    return list(rows)


@router.get("/{supplier_id}/prices", response_model=list[PricePoint])
async def price_history(supplier_id: uuid.UUID, ctx: GM, ingredient_id: uuid.UUID | None = None):
    exists = (await ctx.session.execute(select(Supplier.id).where(
        Supplier.id == supplier_id, Supplier.organisation_id == ctx.organisation_id))).scalar_one_or_none()
    if exists is None:
        raise NotFound("Supplier not found.", code="supplier_not_found")
    q = select(PriceObservation).where(
        PriceObservation.site_id == ctx.site_id, PriceObservation.supplier_id == supplier_id)
    if ingredient_id:
        q = q.where(PriceObservation.ingredient_id == ingredient_id)
    rows = (await ctx.session.execute(q.order_by(PriceObservation.observed_on.desc()).limit(200))).scalars().all()
    return [PricePoint(observed_on=r.observed_on, price_per_base_minor=r.price_per_base_minor,
                       unit_price_minor=r.unit_price_minor, source=r.source) for r in rows]
