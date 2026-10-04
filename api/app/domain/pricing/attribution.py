"""Cost increase attribution (FR-PRC-04, FR-MNU-07).

Period attribution: for a period compared with the prior period of equal length,
delta cost per ingredient = (current price - previous price) x current quantity, aggregated by supplier;
prices are the quantity-weighted normalised prices paid in each period (price observations), quantity is
the theoretical usage in the current period.

Item attribution: which ingredient (and supplier) moved one dish's cost between two dates, from the
daily cost snapshots' per-ingredient breakdown.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.intelligence.models import ItemCostSnapshot
from app.domain.inventory.models import Ingredient, SiteIngredient, StockMovement
from app.domain.purchasing.models import PriceObservation, Supplier, SupplierProduct

ZERO = Decimal(0)


def _pct(part: int, total: int) -> Decimal:
    return (Decimal(part) / Decimal(total) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if total else ZERO


@dataclass(frozen=True)
class AttributionRow:
    ingredient_id: uuid.UUID
    ingredient_name: str
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    previous_price_per_base_minor: Decimal
    current_price_per_base_minor: Decimal
    current_qty_base: Decimal
    delta_cost_minor: int
    pct_of_total: Decimal


@dataclass(frozen=True)
class SupplierAttribution:
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    delta_cost_minor: int
    pct_of_total: Decimal


@dataclass(frozen=True)
class PeriodAttribution:
    current_start: date
    current_end: date
    prior_start: date
    prior_end: date
    total_delta_minor: int
    ingredients: list[AttributionRow]
    suppliers: list[SupplierAttribution]


async def _avg_prices(session: AsyncSession, site_id: uuid.UUID, start: date, end: date
                      ) -> dict[uuid.UUID, tuple[Decimal, uuid.UUID]]:
    """ingredient -> (mean normalised price, supplier with most observations) for the period."""
    rows = (await session.execute(select(
        PriceObservation.ingredient_id, PriceObservation.supplier_id,
        func.avg(PriceObservation.price_per_base_minor), func.count(),
    ).where(PriceObservation.site_id == site_id, PriceObservation.observed_on.between(start, end)).group_by(
        PriceObservation.ingredient_id, PriceObservation.supplier_id))).all()
    acc: dict[uuid.UUID, list] = {}
    for ing, sup, avg, n in rows:
        a = acc.setdefault(ing, [ZERO, 0, sup, 0])
        a[0] += Decimal(avg) * n
        a[1] += n
        if n > a[3]:
            a[2], a[3] = sup, n
    return {i: (a[0] / a[1], a[2]) for i, a in acc.items() if a[1]}


async def attribute_period(session: AsyncSession, *, organisation_id: uuid.UUID, site_id: uuid.UUID,
                           current_start: date, current_end: date) -> PeriodAttribution:
    days = (current_end - current_start).days + 1
    prior_end = current_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=days - 1)
    prev = await _avg_prices(session, site_id, prior_start, prior_end)
    cur = await _avg_prices(session, site_id, current_start, current_end)
    usage = {i: Decimal(q) for i, q in (await session.execute(select(
        StockMovement.ingredient_id, func.sum(-StockMovement.qty_base)).where(
        StockMovement.site_id == site_id, StockMovement.type == "theoretical_consumption",
        StockMovement.business_date.between(current_start, current_end)).group_by(StockMovement.ingredient_id))).all()}
    names = {i: n for i, n in (await session.execute(select(Ingredient.id, Ingredient.name).where(
        Ingredient.organisation_id == organisation_id))).all()}
    suppliers = {i: n for i, n in (await session.execute(select(Supplier.id, Supplier.name).where(
        Supplier.organisation_id == organisation_id))).all()}
    rows: list[AttributionRow] = []
    for ing, (p1, sup) in cur.items():
        if ing not in prev:
            continue
        p0 = prev[ing][0]
        qty = usage.get(ing, ZERO)
        delta = int(((p1 - p0) * qty).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        if delta == 0:
            continue
        rows.append(AttributionRow(ing, names.get(ing, "?"), sup, suppliers.get(sup), p0.quantize(Decimal("0.0001")),
                                   p1.quantize(Decimal("0.0001")), qty, delta, ZERO))
    total = sum(r.delta_cost_minor for r in rows)
    rows = sorted((AttributionRow(**{**r.__dict__, "pct_of_total": _pct(r.delta_cost_minor, total)}) for r in rows),
                  key=lambda r: -r.delta_cost_minor)
    by_supplier: dict[uuid.UUID | None, int] = {}
    for r in rows:
        by_supplier[r.supplier_id] = by_supplier.get(r.supplier_id, 0) + r.delta_cost_minor
    sups = sorted((SupplierAttribution(s, suppliers.get(s) if s else None, d, _pct(d, total))
                   for s, d in by_supplier.items()), key=lambda s: -s.delta_cost_minor)
    return PeriodAttribution(current_start, current_end, prior_start, prior_end, total, rows, sups)


@dataclass(frozen=True)
class ItemDriver:
    ingredient_id: uuid.UUID
    ingredient_name: str
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    cost_from_minor: int
    cost_to_minor: int
    delta_minor: int
    pct_of_change: Decimal


@dataclass(frozen=True)
class ItemAttribution:
    menu_item_id: uuid.UUID
    date_from: date
    date_to: date
    cost_from_minor: int
    cost_to_minor: int
    gp_from_pct: Decimal
    gp_to_pct: Decimal
    drivers: list[ItemDriver]


async def item_attribution(session: AsyncSession, *, organisation_id: uuid.UUID, site_id: uuid.UUID,
                           menu_item_id: uuid.UUID, date_from: date, date_to: date) -> ItemAttribution | None:
    snaps = {s.business_date: s for s in (await session.execute(select(ItemCostSnapshot).where(
        ItemCostSnapshot.site_id == site_id, ItemCostSnapshot.menu_item_id == menu_item_id,
        ItemCostSnapshot.business_date.in_([date_from, date_to])))).scalars()}
    a, b = snaps.get(date_from), snaps.get(date_to)
    if a is None or b is None:
        return None
    keys = set(a.cost_breakdown) | set(b.cost_breakdown)
    ids = [uuid.UUID(k) for k in keys]
    names = {i: n for i, n in (await session.execute(select(Ingredient.id, Ingredient.name).where(
        Ingredient.id.in_(ids)))).all()}
    default_supplier = {i: (s, n) for i, s, n in (await session.execute(select(
        SiteIngredient.ingredient_id, Supplier.id, Supplier.name).join(
        SupplierProduct, SupplierProduct.id == SiteIngredient.default_supplier_product_id).join(
        Supplier, Supplier.id == SupplierProduct.supplier_id).where(
        SiteIngredient.site_id == site_id, SiteIngredient.ingredient_id.in_(ids)))).all()}
    change = b.cost_minor - a.cost_minor
    drivers = []
    for k in keys:
        i = uuid.UUID(k)
        c0, c1 = int(a.cost_breakdown.get(k, 0)), int(b.cost_breakdown.get(k, 0))
        if c0 == c1:
            continue
        sup = default_supplier.get(i, (None, None))
        drivers.append(ItemDriver(i, names.get(i, "?"), sup[0], sup[1], c0, c1, c1 - c0, _pct(c1 - c0, change)))
    drivers.sort(key=lambda d: -abs(d.delta_minor))
    return ItemAttribution(menu_item_id, date_from, date_to, a.cost_minor, b.cost_minor, Decimal(a.gp_pct),
                           Decimal(b.gp_pct), drivers)
