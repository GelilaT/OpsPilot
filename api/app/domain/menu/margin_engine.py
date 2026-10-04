"""Recipe costing, GP and daily snapshots (FR-MNU-02/03).

Item cost at a date = sum over recipe lines of base-unit quantity (already divided by yield and grossed up
by the waste factor) x the ingredient's weighted average cost at the end of that business day. WAC comes
from the stock ledger (FR-STK-09); an ingredient never received at the site falls back to its latest
normalised price observation. Everything is loaded once per site and date range (`CostBook`) so the
nightly job and the seed backfill cost every item for every day with a handful of queries.
"""

import bisect
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy.context import SiteContext
from app.domain.intelligence.models import ItemCostSnapshot
from app.domain.inventory.models import StockMovement
from app.domain.menu.models import MenuItem, MenuItemPrice, Recipe, RecipeLine
from app.domain.purchasing.models import PriceObservation
from app.domain.sales.models import SalesOrderLine
from app.domain.sales.services import ex_vat

ZERO = Decimal(0)
WAC_MOVEMENTS = ("opening", "receipt", "count_adjustment", "transfer")


def gp_pct(price_ex_vat_minor: int, cost_minor: int) -> Decimal:
    if price_ex_vat_minor <= 0:
        return ZERO
    return ((Decimal(price_ex_vat_minor - cost_minor) / Decimal(price_ex_vat_minor)) * 100).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RecipeVersion:
    version: int
    effective_from: date
    effective_to: date | None
    lines: tuple[tuple[uuid.UUID, Decimal], ...]  # (ingredient_id, qty_base_per_portion)


@dataclass(frozen=True)
class PricePeriod:
    effective_from: date
    effective_to: date | None
    price_minor: int
    vat_rate: Decimal


@dataclass(frozen=True)
class ItemCost:
    menu_item_id: uuid.UUID
    business_date: date
    recipe_version: int
    cost_minor: int
    price_ex_vat_minor: int | None
    price_gross_minor: int | None
    vat_rate: Decimal | None
    breakdown: dict[str, int]  # ingredient_id -> minor units per portion
    unit_costs: dict[str, Decimal]  # ingredient_id -> WAC per base unit used

    @property
    def gp_pct(self) -> Decimal | None:
        return None if self.price_ex_vat_minor is None else gp_pct(self.price_ex_vat_minor, self.cost_minor)

    @property
    def cm_minor(self) -> int | None:
        return None if self.price_ex_vat_minor is None else self.price_ex_vat_minor - self.cost_minor


@dataclass
class CostBook:
    """Recipes, menu prices and per-ingredient WAC timelines for one site."""

    tz_close: dict[date, datetime] = field(default_factory=dict)
    items: dict[uuid.UUID, str] = field(default_factory=dict)  # id -> code
    recipes: dict[uuid.UUID, list[RecipeVersion]] = field(default_factory=dict)
    prices: dict[uuid.UUID, list[PricePeriod]] = field(default_factory=dict)
    wac_at: dict[uuid.UUID, list[datetime]] = field(default_factory=dict)
    wac_val: dict[uuid.UUID, list[Decimal]] = field(default_factory=dict)
    obs_on: dict[uuid.UUID, list[date]] = field(default_factory=dict)
    obs_val: dict[uuid.UUID, list[Decimal]] = field(default_factory=dict)

    def recipe(self, menu_item_id: uuid.UUID, on: date) -> RecipeVersion | None:
        best = None
        for r in self.recipes.get(menu_item_id, []):
            if r.effective_from <= on and (r.effective_to is None or r.effective_to > on):
                if best is None or r.version > best.version:
                    best = r
        return best

    def price(self, menu_item_id: uuid.UUID, on: date) -> PricePeriod | None:
        best = None
        for p in self.prices.get(menu_item_id, []):
            if p.effective_from <= on and (p.effective_to is None or p.effective_to > on):
                if best is None or p.effective_from > best.effective_from:
                    best = p
        return best

    def wac(self, ingredient_id: uuid.UUID, at: datetime, on: date) -> Decimal:
        times = self.wac_at.get(ingredient_id)
        if times:
            i = bisect.bisect_left(times, at)
            if i > 0:
                return self.wac_val[ingredient_id][i - 1]
        days = self.obs_on.get(ingredient_id)
        if days:
            i = bisect.bisect_right(days, on)
            if i > 0:
                return self.obs_val[ingredient_id][i - 1]
        return ZERO

    def cost(self, menu_item_id: uuid.UUID, on: date, at: datetime) -> ItemCost:
        recipe = self.recipe(menu_item_id, on)
        period = self.price(menu_item_id, on)
        price_ex = ex_vat(period.price_minor, period.vat_rate) if period else None
        breakdown: dict[str, int] = {}
        units: dict[str, Decimal] = {}
        total = ZERO
        for ingredient_id, qty in recipe.lines if recipe else ():
            unit = self.wac(ingredient_id, at, on)
            part = (qty * unit).quantize(Decimal("0.0001"))
            key = str(ingredient_id)
            breakdown[key] = breakdown.get(key, 0) + int(part.quantize(Decimal(1), rounding=ROUND_HALF_UP))
            units[key] = unit
            total += part
        return ItemCost(
            menu_item_id=menu_item_id, business_date=on, recipe_version=recipe.version if recipe else 0,
            cost_minor=int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP)), price_ex_vat_minor=price_ex,
            price_gross_minor=period.price_minor if period else None, vat_rate=period.vat_rate if period else None,
            breakdown=breakdown, unit_costs=units,
        )


async def load_cost_book(session: AsyncSession, organisation_id: uuid.UUID, site_id: uuid.UUID, *,
                         until: datetime | None = None, menu_item_ids: list[uuid.UUID] | None = None) -> CostBook:
    book = CostBook()
    q = select(MenuItem.id, MenuItem.code).where(MenuItem.organisation_id == organisation_id, MenuItem.active.is_(True))
    if menu_item_ids:
        q = q.where(MenuItem.id.in_(menu_item_ids))
    book.items = {i: c for i, c in (await session.execute(q)).all()}
    ids = list(book.items)

    recipes = (await session.execute(select(Recipe).where(
        Recipe.organisation_id == organisation_id, Recipe.menu_item_id.in_(ids)))).scalars().all()
    lines: dict[uuid.UUID, list[tuple[uuid.UUID, Decimal]]] = defaultdict(list)
    for line in (await session.execute(select(RecipeLine).where(
            RecipeLine.recipe_id.in_([r.id for r in recipes])))).scalars():
        lines[line.recipe_id].append((line.ingredient_id, Decimal(line.qty_base_per_portion)))
    for r in recipes:
        book.recipes.setdefault(r.menu_item_id, []).append(
            RecipeVersion(r.version, r.effective_from, r.effective_to, tuple(lines[r.id])))

    for p in (await session.execute(select(MenuItemPrice).where(
            MenuItemPrice.site_id == site_id, MenuItemPrice.menu_item_id.in_(ids)))).scalars():
        book.prices.setdefault(p.menu_item_id, []).append(
            PricePeriod(p.effective_from, p.effective_to, int(p.price_minor), Decimal(p.vat_rate)))

    ingredient_ids = sorted({i for versions in book.recipes.values() for r in versions for i, _ in r.lines})
    mq = select(StockMovement.ingredient_id, StockMovement.at, StockMovement.unit_cost_minor).where(
        StockMovement.site_id == site_id, StockMovement.ingredient_id.in_(ingredient_ids),
        StockMovement.type.in_(WAC_MOVEMENTS))
    if until is not None:
        mq = mq.where(StockMovement.at < until)
    for ing, at, cost in (await session.execute(mq.order_by(StockMovement.at, StockMovement.id))).all():
        book.wac_at.setdefault(ing, []).append(at)
        book.wac_val.setdefault(ing, []).append(Decimal(cost))
    oq = select(PriceObservation.ingredient_id, PriceObservation.observed_on, PriceObservation.price_per_base_minor).where(
        PriceObservation.site_id == site_id, PriceObservation.ingredient_id.in_(ingredient_ids))
    for ing, on, price in (await session.execute(oq.order_by(PriceObservation.observed_on, PriceObservation.id))).all():
        book.obs_on.setdefault(ing, []).append(on)
        book.obs_val.setdefault(ing, []).append(Decimal(price))
    return book


def end_of_day(ctx: SiteContext, day: date) -> datetime:
    return ctx.local(day, time(23, 59, 59)).astimezone(UTC)


async def cost_at(ctx: SiteContext, menu_item_id: uuid.UUID, on: date) -> ItemCost:
    book = await load_cost_book(ctx.session, ctx.organisation_id, ctx.site_id, menu_item_ids=[menu_item_id])
    return book.cost(menu_item_id, on, end_of_day(ctx, on))


async def units_sold(session: AsyncSession, site_id: uuid.UUID, start: date, end: date,
                     ) -> dict[tuple[uuid.UUID, date], Decimal]:
    rows = await session.execute(select(
        SalesOrderLine.menu_item_id, SalesOrderLine.business_date, func.sum(SalesOrderLine.quantity),
    ).where(SalesOrderLine.site_id == site_id, SalesOrderLine.business_date.between(start, end)).group_by(
        SalesOrderLine.menu_item_id, SalesOrderLine.business_date))
    return {(i, d): Decimal(q) for i, d, q in rows.all()}


async def snapshot_range(ctx: SiteContext, start: date, end: date) -> int:
    """Upsert one ItemCostSnapshot per active menu item and day in [start, end] (idempotent)."""
    book = await load_cost_book(ctx.session, ctx.organisation_id, ctx.site_id)
    sold = await units_sold(ctx.session, ctx.site_id, start, end)
    rows = []
    day = start
    while day <= end:
        at = end_of_day(ctx, day)
        for menu_item_id in book.items:
            c = book.cost(menu_item_id, day, at)
            if c.price_ex_vat_minor is None:
                continue
            units = sold.get((menu_item_id, day), ZERO)
            cm = c.cm_minor or 0
            rows.append({
                "id": uuid.uuid4(), "organisation_id": ctx.organisation_id, "site_id": ctx.site_id,
                "menu_item_id": menu_item_id, "business_date": day, "recipe_version": c.recipe_version,
                "price_ex_vat_minor": c.price_ex_vat_minor, "cost_minor": c.cost_minor, "gp_pct": c.gp_pct,
                "cm_minor": cm, "cost_breakdown": c.breakdown, "units_sold": units,
                "total_contribution_minor": int((Decimal(cm) * units).quantize(Decimal(1), rounding=ROUND_HALF_UP)),
            })
        day += timedelta(days=1)
    written = 0
    for i in range(0, len(rows), 2000):
        stmt = insert(ItemCostSnapshot).values(rows[i:i + 2000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["site_id", "menu_item_id", "business_date"],
            set_={k: getattr(stmt.excluded, k) for k in (
                "recipe_version", "price_ex_vat_minor", "cost_minor", "gp_pct", "cm_minor", "cost_breakdown",
                "units_sold", "total_contribution_minor")},
        )
        await ctx.session.execute(stmt)
        written += len(rows[i:i + 2000])
    return written


async def snapshot_site_day(ctx: SiteContext, day: date) -> int:
    return await snapshot_range(ctx, day, day)
