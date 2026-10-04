"""Purchase orders (FR-PRC-07/08): draft and committed POs; commit by a role within its PO limit."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import site_context
from app.api.v1.actions import role_of
from app.core.errors import NotFound, PreconditionFailed
from app.core.security import Role
from app.core.tenancy.context import SiteContext
from app.core.tenancy.services import actor_label, actor_names
from app.domain.notifications.models import EmailDelivery
from app.domain.purchasing.models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierProduct
from app.domain.purchasing.orders import commit_po

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])
Chef = Annotated[SiteContext, Depends(site_context(Role.head_chef))]


class POLineOut(BaseModel):
    product: str
    sku: str
    qty_units: Decimal
    qty_base: Decimal
    unit_price_minor: int
    line_total_minor: int
    reason_codes: list[str]


class POOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    number: str
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    status: str
    order_date: date
    expected_delivery_date: date
    subtotal_minor: int
    currency: str
    approved_by: str | None
    committed_at: datetime | None
    recommendation_id: uuid.UUID | None
    version: int


class PODetail(POOut):
    approved_by_name: str | None = None
    lines: list[POLineOut]
    emails: list[dict]


@router.get("", response_model=list[POOut])
async def list_pos(ctx: Chef, status: str | None = None, recommendation_id: uuid.UUID | None = None,
                   limit: int = Query(50, le=200)):
    q = select(PurchaseOrder, Supplier.name).join(Supplier, Supplier.id == PurchaseOrder.supplier_id).where(
        PurchaseOrder.site_id == ctx.site_id)
    if status:
        q = q.where(PurchaseOrder.status.in_(status.split(",")))
    if recommendation_id:
        q = q.where(PurchaseOrder.recommendation_id == recommendation_id)
    rows = (await ctx.session.execute(q.order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.number.desc())
                                      .limit(limit))).all()
    return [POOut.model_validate(po).model_copy(update={"supplier_name": name}) for po, name in rows]


async def _po(ctx: SiteContext, po_id: uuid.UUID, *, lock: bool = False) -> PurchaseOrder:
    q = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.site_id == ctx.site_id)
    po = (await ctx.session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if po is None:
        raise NotFound("Purchase order not found.", code="purchase_order_not_found")
    return po


async def _detail(ctx: SiteContext, po: PurchaseOrder) -> PODetail:
    name = (await ctx.session.execute(select(Supplier.name).where(Supplier.id == po.supplier_id))).scalar_one()
    lines = (await ctx.session.execute(select(PurchaseOrderLine, SupplierProduct).join(
        SupplierProduct, SupplierProduct.id == PurchaseOrderLine.supplier_product_id).where(
        PurchaseOrderLine.purchase_order_id == po.id))).all()
    emails = (await ctx.session.execute(select(EmailDelivery).where(EmailDelivery.related_id == po.id))).scalars()
    names = await actor_names(ctx.session, [po.approved_by])
    return PODetail(**POOut.model_validate(po).model_dump(exclude={"supplier_name"}), supplier_name=name,
                    approved_by_name=actor_label(names, po.approved_by),
                    lines=[POLineOut(product=p.name, sku=p.sku, qty_units=line.qty_units, qty_base=line.qty_base,
                                     unit_price_minor=line.unit_price_minor, line_total_minor=line.line_total_minor,
                                     reason_codes=line.reason_codes) for line, p in lines],
                    emails=[{"to": e.to, "status": e.status, "attempts": e.attempts, "provider": e.provider,
                             "sent_at": e.sent_at, "error": e.last_error} for e in emails])


@router.get("/{po_id}", response_model=PODetail)
async def get_po(po_id: uuid.UUID, ctx: Chef):
    return await _detail(ctx, await _po(ctx, po_id))


@router.post("/{po_id}/approve", response_model=PODetail)
async def approve_po(po_id: uuid.UUID, ctx: Chef, if_match: Annotated[str | None, Header()] = None):
    po = await _po(ctx, po_id, lock=True)
    if if_match is not None and if_match.strip('"W/') != str(po.version):
        raise PreconditionFailed("The purchase order changed; reload and try again.", code="stale_version")
    await commit_po(ctx, po, approver=ctx.actor, approver_role=role_of(ctx))
    return await _detail(ctx, po)
