"""Daily trading facts per site loaded in a few grouped queries (shared by detectors and investigations)."""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inventory.models import StockMovement
from app.domain.sales.models import CashUp, SalesOrder, SalesOrderLine, Shift

ZERO = Decimal(0)


@dataclass
class DayFacts:
    day: date
    orders: int = 0
    covers: int = 0
    revenue: int = 0  # net, ex VAT
    gross: int = 0  # before discounts, VAT inclusive
    discount: int = 0
    void: int = 0
    labour_cost: int = 0
    labour_hours: Decimal = ZERO
    cogs: int = 0  # theoretical ingredient cost of the day's sales
    cash_variance: int | None = None
    daypart_revenue: dict[str, int] = field(default_factory=dict)
    daypart_orders: dict[str, int] = field(default_factory=dict)
    item_units: dict[uuid.UUID, Decimal] = field(default_factory=dict)
    item_revenue: dict[uuid.UUID, int] = field(default_factory=dict)

    @property
    def traded(self) -> bool:
        return self.orders > 0

    @property
    def spend(self) -> Decimal:
        return Decimal(self.revenue) / self.orders if self.orders else ZERO

    def rate(self, part: int) -> Decimal:
        return Decimal(part) / Decimal(self.gross) if self.gross else ZERO


async def load_days(session: AsyncSession, site_id: uuid.UUID, days: list[date]) -> dict[date, DayFacts]:
    out = {d: DayFacts(d) for d in days}
    if not days:
        return out
    for d, dp, n, covers, rev, gross, disc, void in (await session.execute(select(
        SalesOrder.business_date, SalesOrder.daypart, func.count(), func.sum(SalesOrder.covers),
        func.sum(SalesOrder.revenue_ex_vat_minor), func.sum(SalesOrder.gross_minor),
        func.sum(SalesOrder.discount_minor), func.sum(SalesOrder.void_minor),
    ).where(SalesOrder.site_id == site_id, SalesOrder.business_date.in_(days)).group_by(
        SalesOrder.business_date, SalesOrder.daypart))).all():
        f = out[d]
        f.orders += n
        f.covers += int(covers or 0)
        f.revenue += int(rev or 0)
        f.gross += int(gross or 0)
        f.discount += int(disc or 0)
        f.void += int(void or 0)
        f.daypart_revenue[dp] = f.daypart_revenue.get(dp, 0) + int(rev or 0)
        f.daypart_orders[dp] = f.daypart_orders.get(dp, 0) + n
    for d, item, units, rev in (await session.execute(select(
        SalesOrderLine.business_date, SalesOrderLine.menu_item_id, func.sum(SalesOrderLine.quantity),
        func.sum(SalesOrderLine.revenue_ex_vat_minor),
    ).where(SalesOrderLine.site_id == site_id, SalesOrderLine.business_date.in_(days)).group_by(
        SalesOrderLine.business_date, SalesOrderLine.menu_item_id))).all():
        out[d].item_units[item] = Decimal(units or 0)
        out[d].item_revenue[item] = int(rev or 0)
    for d, cost, hours in (await session.execute(select(
        Shift.business_date, func.sum(Shift.cost_minor), func.sum(Shift.hours),
    ).where(Shift.site_id == site_id, Shift.business_date.in_(days)).group_by(Shift.business_date))).all():
        out[d].labour_cost = int(cost or 0)
        out[d].labour_hours = Decimal(hours or 0)
    for d, cost in (await session.execute(select(
        StockMovement.business_date, func.sum(-StockMovement.cost_minor),
    ).where(StockMovement.site_id == site_id, StockMovement.business_date.in_(days),
            StockMovement.type == "theoretical_consumption").group_by(StockMovement.business_date))).all():
        out[d].cogs = int(cost or 0)
    for d, var in (await session.execute(select(CashUp.business_date, CashUp.variance_minor).where(
            CashUp.site_id == site_id, CashUp.business_date.in_(days)))).all():
        out[d].cash_variance = int(var)
    return out


def merge_units(facts: list[DayFacts]) -> dict[uuid.UUID, list[Decimal]]:
    series: dict[uuid.UUID, list[Decimal]] = defaultdict(list)
    for f in facts:
        for item, units in f.item_units.items():
            series[item].append(units)
    return series
