"""Purchase orders raised by the agent (FR-PRC-07/08).

Draft POs carry recommended packs, expected price and cost and reason codes. A PO is committed only by a
role whose PO approval limit covers its value (`approval.po_limits`); on commit it is emailed to the
supplier through the MailPort. Nothing is ordered automatically.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select

from app.core.audit import record_audit
from app.core.errors import Conflict, Forbidden
from app.core.tenancy.context import SiteContext
from app.domain.notifications.email_format import render_po_email
from app.domain.notifications.service import queue_email
from app.domain.purchasing.invoice_rules import ROLE_RANK, within_limit
from app.domain.purchasing.models import PriceObservation, PurchaseOrder, PurchaseOrderLine, Supplier, SupplierProduct

ZERO = Decimal(0)


@dataclass(frozen=True)
class PoLineDraft:
    product: SupplierProduct
    qty_base: Decimal
    reason_codes: tuple[str, ...]


async def latest_unit_price(ctx: SiteContext, product: SupplierProduct, on: date) -> int | None:
    return (await ctx.session.execute(select(PriceObservation.unit_price_minor).where(
        PriceObservation.site_id == ctx.site_id, PriceObservation.supplier_product_id == product.id,
        PriceObservation.observed_on <= on).order_by(PriceObservation.observed_on.desc(),
                                                     PriceObservation.id.desc()).limit(1))).scalar_one_or_none()


def packs_for(qty_base: Decimal, product: SupplierProduct) -> Decimal:
    packs = (qty_base / product.base_qty_per_unit).to_integral_value(rounding=ROUND_CEILING)
    return max(packs, Decimal(product.moq_units or 1))


def next_delivery(supplier: Supplier, today: date) -> date:
    day = today + timedelta(days=max(supplier.lead_time_days, 1))
    weekdays = supplier.delivery_weekdays or list(range(7))
    while day.weekday() not in weekdays:
        day += timedelta(days=1)
    return day


async def create_draft_po(ctx: SiteContext, *, supplier: Supplier, lines: list[PoLineDraft], number_ref: str,
                          recommendation_id: uuid.UUID | None, notes: str | None = None) -> PurchaseOrder:
    today = await ctx.today()
    po = PurchaseOrder(
        organisation_id=ctx.organisation_id, site_id=ctx.site_id, number=f"PO-{number_ref}",
        supplier_id=supplier.id, status="draft", order_date=today, expected_delivery_date=next_delivery(supplier, today),
        currency=ctx.currency, subtotal_minor=0, created_by=ctx.actor, recommendation_id=recommendation_id,
        notes=notes, version=1,
    )
    ctx.session.add(po)
    await ctx.session.flush()
    subtotal = 0
    for line in lines:
        packs = packs_for(line.qty_base, line.product)
        price = await latest_unit_price(ctx, line.product, today)
        if price is None:
            raise Conflict(f"No known price for {line.product.name}.", code="no_price")
        total = int(packs * price)
        subtotal += total
        ctx.session.add(PurchaseOrderLine(
            organisation_id=ctx.organisation_id, site_id=ctx.site_id, purchase_order_id=po.id,
            supplier_product_id=line.product.id, ingredient_id=line.product.ingredient_id, qty_units=packs,
            qty_base=packs * line.product.base_qty_per_unit, unit_price_minor=price, line_total_minor=total,
            reason_codes=list(line.reason_codes)))
    po.subtotal_minor = subtotal
    record_audit(ctx.session, actor=ctx.actor, entity_type="purchase_order", entity_id=po.id, action="create_draft",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                 after={"number": po.number, "subtotal_minor": subtotal, "recommendation_id": str(recommendation_id)})
    await ctx.session.flush()
    return po


def can_commit(role: str, po: PurchaseOrder, limits: dict[str, int | None]) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK["head_chef"] and within_limit(role, po.subtotal_minor, limits)


async def commit_po(ctx: SiteContext, po: PurchaseOrder, *, approver: str, approver_role: str,
                    email: bool = True) -> PurchaseOrder:
    """FR-PRC-08: commit within the approver's limit, then email the supplier."""
    if po.status not in ("draft", "pending_approval"):
        raise Conflict(f"A purchase order in state {po.status!r} cannot be committed.", code="illegal_transition")
    limits = ctx.config.get("approval.po_limits").model_dump()
    if not can_commit(approver_role, po, limits):
        raise Forbidden("This purchase order is above your approval limit.", code="approval_limit")
    before = po.status
    now = datetime.now(UTC)
    po.status, po.approved_by, po.approved_at, po.committed_at = "committed", approver, now, now
    po.version += 1
    record_audit(ctx.session, actor=ctx.actor, entity_type="purchase_order", entity_id=po.id, action="commit",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id, before={"status": before},
                 after={"status": "committed", "approved_by": approver, "subtotal_minor": po.subtotal_minor})
    supplier = (await ctx.session.execute(select(Supplier).where(Supplier.id == po.supplier_id))).scalar_one()
    if email and supplier.email:
        text, html = await po_email_bodies(ctx, po, supplier)
        await queue_email(ctx, key=f"po:{po.id}:commit", to=[supplier.email], subject=f"Purchase order {po.number}",
                          text=text, html=html, ref={"type": "purchase_order", "id": str(po.id)}, related_id=po.id)
    await ctx.session.flush()
    return po


async def po_email_bodies(ctx: SiteContext, po: PurchaseOrder, supplier: Supplier) -> tuple[str, str]:
    rows_db = (await ctx.session.execute(select(PurchaseOrderLine, SupplierProduct).join(
        SupplierProduct, SupplierProduct.id == PurchaseOrderLine.supplier_product_id).where(
        PurchaseOrderLine.purchase_order_id == po.id))).all()
    table_rows = [
        [f"{line.qty_units.normalize():f}", product.name, product.sku,
         f"{line.unit_price_minor / 100:.2f}", f"{line.line_total_minor / 100:.2f} {po.currency}"]
        for line, product in rows_db
    ]
    intro = (f"Please supply the following for delivery on "
             f"{po.expected_delivery_date.strftime('%A %d %B %Y')} to {ctx.site.name}.")
    summary = [
        f"Order total (ex VAT): {po.subtotal_minor / 100:.2f} {po.currency}",
        f"Reference: {po.number}",
        f"Approved by {po.approved_by}.",
    ]
    footer = f"Sent by OpsPilot on behalf of {ctx.site.name}"
    return render_po_email(
        greeting=f"Dear {supplier.name},",
        intro=intro,
        table_headers=["Qty", "Product", "SKU", "Unit price", "Line total"],
        table_rows=table_rows,
        summary_lines=summary,
        footer=footer,
    )
