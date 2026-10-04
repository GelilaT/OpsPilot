"""Intraday stock-out reconstruction from the ledger and sales timestamps (detector `stock_out`, hypothesis
`ingredient_stock_out`).

On-hand at the start of the business day comes from the ledger; receipts carry their arrival time; each
sale consumes its recipe quantity at `sold_at`. An ingredient is out when what is left cannot serve a
table (two portions of the dish that needs the most of it), while those dishes normally keep selling later in the day (the
same weekday's baseline). The lost sales are the baseline units after that time.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from sqlalchemy import func, select

from app.core.tenancy.context import SiteContext
from app.domain.inventory.models import Ingredient, StockMovement
from app.domain.menu.models import MenuItem, Recipe, RecipeLine
from app.domain.sales.models import SalesOrderLine

ZERO = Decimal(0)


@dataclass(frozen=True)
class StockOutEvent:
    ingredient_id: uuid.UUID
    ingredient_code: str
    ingredient_name: str
    base_unit: str
    out_at: datetime  # local time of the last portion sold
    on_hand_left: Decimal  # what remained (less than one portion of the largest dish)
    opening_qty: Decimal
    received_qty: Decimal
    first_receipt_at: datetime | None
    dependent_items: dict[uuid.UUID, str]  # id -> name
    lost_units: dict[uuid.UUID, Decimal]  # baseline units after out_at
    need_after_qty: Decimal  # ingredient the lost units would have used
    sold_after_qty: Decimal  # dependent units actually sold after out_at (should be ~0)


def closing_time(ctx: SiteContext) -> time:
    """End of the last trading daypart (site configuration)."""
    return max(d.end for d in ctx.config.get("site.dayparts"))


async def recipe_uses(ctx: SiteContext, day: date) -> dict[uuid.UUID, dict[uuid.UUID, Decimal]]:
    """menu item -> {ingredient -> base qty per portion} for the recipes active on `day`."""
    rows = (await ctx.session.execute(select(Recipe.menu_item_id, RecipeLine.ingredient_id,
                                             RecipeLine.qty_base_per_portion).join(
        RecipeLine, RecipeLine.recipe_id == Recipe.id).where(
        Recipe.organisation_id == ctx.organisation_id, Recipe.effective_from <= day,
        (Recipe.effective_to.is_(None)) | (Recipe.effective_to > day)))).all()
    out: dict[uuid.UUID, dict[uuid.UUID, Decimal]] = defaultdict(dict)
    for item, ing, qty in rows:
        out[item][ing] = out[item].get(ing, ZERO) + Decimal(qty)
    return out


async def find_stock_outs(ctx: SiteContext, day: date, baseline_days: list[date],
                          *, ingredient_ids: set[uuid.UUID] | None = None) -> list[StockOutEvent]:
    s = ctx.session
    start = ctx.local(day, time(0)).astimezone(UTC)
    uses = await recipe_uses(ctx, day)
    by_ingredient: dict[uuid.UUID, dict[uuid.UUID, Decimal]] = defaultdict(dict)
    for item, lines in uses.items():
        for ing, qty in lines.items():
            by_ingredient[ing][item] = qty
    candidates = set(by_ingredient) if ingredient_ids is None else set(by_ingredient) & ingredient_ids
    if not candidates:
        return []
    opening = {i: Decimal(q) for i, q in (await s.execute(select(
        StockMovement.ingredient_id, func.sum(StockMovement.qty_base)).where(
        StockMovement.site_id == ctx.site_id, StockMovement.at < start,
        StockMovement.ingredient_id.in_(candidates)).group_by(StockMovement.ingredient_id))).all()}
    receipts: dict[uuid.UUID, list[tuple[datetime, Decimal]]] = defaultdict(list)
    for ing, at, qty in (await s.execute(select(StockMovement.ingredient_id, StockMovement.at, StockMovement.qty_base).where(
            StockMovement.site_id == ctx.site_id, StockMovement.business_date == day, StockMovement.type == "receipt",
            StockMovement.ingredient_id.in_(candidates)))).all():
        receipts[ing].append((at, Decimal(qty)))
    sales = (await s.execute(select(SalesOrderLine.sold_at, SalesOrderLine.menu_item_id, SalesOrderLine.quantity).where(
        SalesOrderLine.site_id == ctx.site_id, SalesOrderLine.business_date == day,
        SalesOrderLine.quantity > 0).order_by(SalesOrderLine.sold_at))).all()

    close = closing_time(ctx)
    events: list[StockOutEvent] = []
    for ing in candidates:
        items = by_ingredient[ing]
        # Out when what is left cannot serve a table (two portions of the dish needing the most) and the
        # dishes stop selling; a single portion left on the shelf is not service-ready stock.
        portion = 2 * max(items.values())
        timeline: list[tuple[datetime, Decimal, uuid.UUID | None]] = [(at, q, None) for at, q in receipts[ing]]
        timeline += [(at, -Decimal(q) * items[item], item) for at, item, q in sales if item in items]
        timeline.sort(key=lambda e: (e[0], e[1] < 0))
        on_hand = opening.get(ing, ZERO)
        out_at: datetime | None = None
        left = ZERO
        for _at, delta, item in timeline:
            on_hand += delta
            if item is not None and on_hand < portion:
                out_at, left = _at, on_hand
            elif item is None and on_hand >= portion:
                out_at = None  # a later receipt replenished it
        if out_at is None:
            continue
        local_out = out_at.astimezone(ctx.tz)
        if local_out.time() >= close:
            continue
        lost = await _baseline_units_after(ctx, baseline_days, list(items), local_out.time())
        if not lost or sum(lost.values()) < 1:
            continue
        sold_after = sum((Decimal(q) * items[item] for at, item, q in sales
                          if item in items and at > out_at), ZERO)
        events.append(StockOutEvent(
            ingredient_id=ing, ingredient_code="", ingredient_name="", base_unit="",
            out_at=local_out, on_hand_left=max(left, ZERO), opening_qty=opening.get(ing, ZERO),
            received_qty=sum((q for _, q in receipts[ing]), ZERO),
            first_receipt_at=min((a for a, _ in receipts[ing]), default=None),
            dependent_items={i: "" for i in items}, lost_units=lost,
            need_after_qty=sum((u * items[i] for i, u in lost.items()), ZERO).quantize(Decimal("0.1"),
                                                                                        rounding=ROUND_HALF_UP),
            sold_after_qty=sold_after,
        ))
    if not events:
        return []
    names = {i: (c, n, u) for i, c, n, u in (await s.execute(select(
        Ingredient.id, Ingredient.code, Ingredient.name, Ingredient.base_unit).where(
        Ingredient.id.in_([e.ingredient_id for e in events])))).all()}
    item_names = {i: n for i, n in (await s.execute(select(MenuItem.id, MenuItem.name).where(
        MenuItem.organisation_id == ctx.organisation_id))).all()}
    return [StockOutEvent(**{**e.__dict__, "ingredient_code": names[e.ingredient_id][0],
                             "ingredient_name": names[e.ingredient_id][1], "base_unit": names[e.ingredient_id][2],
                             "dependent_items": {i: item_names.get(i, "?") for i in e.dependent_items}})
            for e in events]


async def _baseline_units_after(ctx: SiteContext, baseline_days: list[date], items: list[uuid.UUID],
                                after: time) -> dict[uuid.UUID, Decimal]:
    """Median units per item sold after `after` (local time) on the baseline days."""
    if not baseline_days:
        return {}
    rows = (await ctx.session.execute(select(
        SalesOrderLine.business_date, SalesOrderLine.menu_item_id, SalesOrderLine.sold_at, SalesOrderLine.quantity,
    ).where(SalesOrderLine.site_id == ctx.site_id, SalesOrderLine.business_date.in_(baseline_days),
            SalesOrderLine.menu_item_id.in_(items)))).all()
    per: dict[uuid.UUID, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    traded = {d for d, *_ in rows}
    for d, item, at, q in rows:
        if at.astimezone(ctx.tz).time() > after:
            per[item][d] += Decimal(q)
    out = {}
    for item in items:
        series = [per[item].get(d, ZERO) for d in baseline_days if d in traded]
        if series:
            m = Decimal(str(median(series)))
            if m > 0:
                out[item] = m
    return out
