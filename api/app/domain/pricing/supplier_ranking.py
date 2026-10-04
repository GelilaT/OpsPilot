"""Supplier comparison by normalised price, fill rate and lead time (FR-PRC-03) and the supplier-switch
rule (FR-PRC-10).

Fill rate = received / ordered over the window, for purchase-order lines that were due for delivery in
the window. Quantities are compared per line (so grams and eaches never mix) and weighted by the line's
ordered value.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.purchasing.invoice_models import Invoice, InvoiceLine
from app.domain.purchasing.models import (
    GoodsReceiptLine,
    PriceObservation,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierProduct,
)

ZERO = Decimal(0)
OPEN_PO = ("committed", "sent", "part_received", "received")


@dataclass(frozen=True)
class FillRate:
    supplier_id: uuid.UUID
    rate: Decimal
    lines: int
    ordered_value_minor: int
    short_lines: int


async def fill_rates(session: AsyncSession, site_id: uuid.UUID, start: date, end: date,
                     *, ingredient_id: uuid.UUID | None = None) -> dict[uuid.UUID, FillRate]:
    received = (select(GoodsReceiptLine.purchase_order_line_id.label("line_id"),
                       func.sum(GoodsReceiptLine.qty_base).label("qty"))
                .where(GoodsReceiptLine.site_id == site_id).group_by(GoodsReceiptLine.purchase_order_line_id)
                .subquery())
    invoiced = (select(Invoice.purchase_order_id.label("po_id"), InvoiceLine.ingredient_id.label("ingredient_id"),
                       func.sum(InvoiceLine.qty_base).label("qty"))
                .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
                .where(Invoice.site_id == site_id, Invoice.status == "posted", Invoice.purchase_order_id.is_not(None))
                .group_by(Invoice.purchase_order_id, InvoiceLine.ingredient_id).subquery())
    # Goods received; when the invoice was posted before the goods were recorded, the invoiced quantity.
    got = func.coalesce(received.c.qty, invoiced.c.qty, 0)
    q = select(PurchaseOrder.supplier_id, PurchaseOrderLine.qty_base, PurchaseOrderLine.line_total_minor, got).join(
        PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id).outerjoin(
        received, received.c.line_id == PurchaseOrderLine.id).outerjoin(
        invoiced, (invoiced.c.po_id == PurchaseOrder.id) & (invoiced.c.ingredient_id == PurchaseOrderLine.ingredient_id)
    ).where(
        PurchaseOrder.site_id == site_id, PurchaseOrder.status.in_(OPEN_PO),
        PurchaseOrder.expected_delivery_date.between(start, end))
    if ingredient_id is not None:
        q = q.where(PurchaseOrderLine.ingredient_id == ingredient_id)
    acc: dict[uuid.UUID, list] = {}
    for supplier_id, ordered, value, got in (await session.execute(q)).all():
        if ordered is None or Decimal(ordered) <= 0:
            continue
        ratio = min(Decimal(got) / Decimal(ordered), Decimal(1))
        weight = Decimal(max(int(value or 0), 1))
        a = acc.setdefault(supplier_id, [ZERO, ZERO, 0, 0])
        a[0] += ratio * weight
        a[1] += weight
        a[2] += 1
        a[3] += 1 if ratio < Decimal("0.98") else 0
    return {s: FillRate(s, (num / den).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP), n, int(den), short)
            for s, (num, den, n, short) in acc.items() if den > 0}


@dataclass(frozen=True)
class SupplierOffer:
    supplier_id: uuid.UUID
    supplier_name: str
    supplier_product_id: uuid.UUID
    product_name: str
    price_per_base_minor: Decimal | None
    price_observed_on: date | None
    fill_rate: Decimal | None
    lead_time_days: int
    rank: int = 0


async def rank_for_ingredient(
    session: AsyncSession,
    organisation_id: uuid.UUID,
    site_id: uuid.UUID,
    ingredient_id: uuid.UUID,
    *,
    as_of: date,
    window_days: int = 90,
) -> list[SupplierOffer]:
    """Latest normalised price, 90-day fill rate and lead time per supplier offering the ingredient,
    ranked by price, then fill rate, then lead time."""
    products = (await session.execute(select(SupplierProduct, Supplier).join(
        Supplier, Supplier.id == SupplierProduct.supplier_id).where(
        SupplierProduct.ingredient_id == ingredient_id,
        SupplierProduct.organisation_id == organisation_id,
        SupplierProduct.active.is_(True),
        Supplier.active.is_(True),
    ))).all()
    rates = await fill_rates(session, site_id, as_of - timedelta(days=window_days), as_of)
    offers: list[SupplierOffer] = []
    for product, supplier in products:
        latest = (await session.execute(select(PriceObservation.price_per_base_minor, PriceObservation.observed_on).where(
            PriceObservation.site_id == site_id,
            PriceObservation.supplier_product_id == product.id,
            PriceObservation.observed_on <= as_of,
        ).order_by(PriceObservation.observed_on.desc(), PriceObservation.id.desc()).limit(1))).first()
        rate = rates.get(supplier.id)
        offers.append(SupplierOffer(
            supplier.id, supplier.name, product.id, product.name,
            Decimal(latest[0]) if latest else None, latest[1] if latest else None,
            rate.rate if rate else None, supplier.lead_time_days,
        ))
    offers.sort(key=lambda o: (o.price_per_base_minor is None, o.price_per_base_minor or ZERO,
                               -(o.fill_rate or ZERO), o.lead_time_days))
    return [SupplierOffer(**{**o.__dict__, "rank": i + 1}) for i, o in enumerate(offers)]


@dataclass(frozen=True)
class SwitchCandidate:
    incumbent: SupplierOffer
    alternative: SupplierOffer
    saving_pct: Decimal
    price_delta_per_base_minor: Decimal


def switch_candidate(offers: list[SupplierOffer], incumbent_supplier_id: uuid.UUID, *, min_saving_pct: Decimal,
                     min_fill_rate: Decimal) -> SwitchCandidate | None:
    """FR-PRC-10: an alternative at least `min_saving_pct` cheaper with fill rate >= `min_fill_rate`.
    An alternative with no deliveries in the window uses its supplier-wide fill rate if known."""
    current = next((o for o in offers if o.supplier_id == incumbent_supplier_id), None)
    if current is None or current.price_per_base_minor is None or current.price_per_base_minor <= 0:
        return None
    best: SwitchCandidate | None = None
    for o in offers:
        if o.supplier_id == incumbent_supplier_id or o.price_per_base_minor is None:
            continue
        if o.fill_rate is None or o.fill_rate < min_fill_rate:
            continue
        saving = (current.price_per_base_minor - o.price_per_base_minor) / current.price_per_base_minor
        if saving < min_saving_pct:
            continue
        if best is None or saving > best.saving_pct:
            best = SwitchCandidate(current, o, saving.quantize(Decimal("0.0001")),
                                   current.price_per_base_minor - o.price_per_base_minor)
    return best
