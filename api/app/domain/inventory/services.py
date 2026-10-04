"""Stock ledger services: derived on-hand, weighted average cost (FR-STK-09), receipts and nightly
theoretical consumption from sales x the recipe version active on the sale date (FR-STK-03)."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, func, select, text
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy.context import SiteContext
from app.domain.inventory.models import SiteIngredient, StockMovement
from app.domain.inventory.rules import money_minor, new_wac

ZERO = Decimal(0)


async def on_hand(session: AsyncSession, site_id: uuid.UUID, *, at: datetime | None = None,
                  ingredient_ids: list[uuid.UUID] | None = None) -> dict[uuid.UUID, Decimal]:
    q = select(StockMovement.ingredient_id, func.sum(StockMovement.qty_base)).where(StockMovement.site_id == site_id)
    if at is not None:
        q = q.where(StockMovement.at < at)
    if ingredient_ids:
        q = q.where(StockMovement.ingredient_id.in_(ingredient_ids))
    rows = await session.execute(q.group_by(StockMovement.ingredient_id))
    return {i: Decimal(v) for i, v in rows.all()}


async def current_wac(session: AsyncSession, site_id: uuid.UUID, *, at: datetime | None = None,
                      ingredient_ids: list[uuid.UUID] | None = None) -> dict[uuid.UUID, Decimal]:
    """WAC in effect = unit cost of each ingredient's latest movement (before `at`)."""
    q = select(StockMovement.ingredient_id, StockMovement.unit_cost_minor).where(StockMovement.site_id == site_id)
    if at is not None:
        q = q.where(StockMovement.at < at)
    if ingredient_ids:
        q = q.where(StockMovement.ingredient_id.in_(ingredient_ids))
    q = q.ext(distinct_on(StockMovement.ingredient_id)).order_by(StockMovement.ingredient_id, StockMovement.at.desc(),
                                                         StockMovement.id.desc())
    return {i: Decimal(c) for i, c in (await session.execute(q)).all()}


@dataclass(frozen=True)
class ReceiptLine:
    ingredient_id: uuid.UUID
    qty_base: Decimal
    price_per_base_minor: Decimal


async def post_receipts(ctx: SiteContext, *, lines: list[ReceiptLine], at: datetime, business_date: date,
                        ref_type: str, ref_id: str) -> int:
    """Book receipts with WAC update. Idempotent per (ingredient, ref): a replay inserts nothing."""
    if not lines:
        return 0
    ids = sorted({line.ingredient_id for line in lines})
    # Serialise WAC updates per ingredient at this site.
    await ctx.session.execute(select(SiteIngredient.id).where(
        SiteIngredient.site_id == ctx.site_id, SiteIngredient.ingredient_id.in_(ids)).with_for_update())
    stock = await on_hand(ctx.session, ctx.site_id, ingredient_ids=ids)
    wacs = await current_wac(ctx.session, ctx.site_id, ingredient_ids=ids)
    merged: dict[uuid.UUID, tuple[Decimal, Decimal]] = {}
    for line in lines:  # several invoice lines for one ingredient -> one movement at their weighted price
        qty, value = merged.get(line.ingredient_id, (ZERO, ZERO))
        merged[line.ingredient_id] = (qty + line.qty_base, value + line.qty_base * line.price_per_base_minor)
    posted = 0
    for ingredient_id, (qty, value) in merged.items():
        if qty <= 0:
            continue
        price = (value / qty).quantize(Decimal("0.000001"))
        wac = new_wac(stock.get(ingredient_id, ZERO), wacs.get(ingredient_id, price), qty, price)
        result = await ctx.session.execute(insert(StockMovement).values(
            organisation_id=ctx.organisation_id, site_id=ctx.site_id, ingredient_id=ingredient_id, at=at,
            business_date=business_date, type="receipt", qty_base=qty, unit_cost_minor=wac,
            cost_minor=money_minor(qty, price), ref_type=ref_type, ref_id=ref_id,
        ).on_conflict_do_nothing(index_elements=["site_id", "ingredient_id", "type", "ref_type", "ref_id"]))
        posted += getattr(result, "rowcount", 0) or 0
    return posted


THEORETICAL_SQL = text("""
    SELECT rl.ingredient_id, SUM(sol.quantity * rl.qty_base_per_portion) AS qty
    FROM sales_order_line sol
    JOIN recipe r ON r.menu_item_id = sol.menu_item_id
                 AND r.effective_from <= sol.business_date
                 AND (r.effective_to IS NULL OR r.effective_to > sol.business_date)
    JOIN recipe_line rl ON rl.recipe_id = r.id
    WHERE sol.site_id = :site AND sol.business_date = :day AND sol.quantity > 0
    GROUP BY rl.ingredient_id
""")


async def theoretical_usage(session: AsyncSession, site_id: uuid.UUID, day: date) -> dict[uuid.UUID, Decimal]:
    rows = await session.execute(THEORETICAL_SQL, {"site": site_id, "day": day})
    return {i: Decimal(q) for i, q in rows.all() if q}


async def post_theoretical_consumption(ctx: SiteContext, day: date, at: datetime) -> int:
    """Nightly: one negative movement per ingredient for the day's sales (idempotent per day)."""
    usage = await theoretical_usage(ctx.session, ctx.site_id, day)
    wacs = await current_wac(ctx.session, ctx.site_id, at=at)
    rows = [{
        "organisation_id": ctx.organisation_id, "site_id": ctx.site_id, "ingredient_id": ing, "at": at,
        "business_date": day, "type": "theoretical_consumption", "qty_base": -qty,
        "unit_cost_minor": wacs.get(ing, ZERO), "cost_minor": -money_minor(qty, wacs.get(ing, ZERO)),
        "ref_type": "sales_day", "ref_id": day.isoformat(),
    } for ing, qty in usage.items()]
    if not rows:
        return 0
    result = await ctx.session.execute(insert(StockMovement).values(rows).on_conflict_do_nothing(
        index_elements=["site_id", "ingredient_id", "type", "ref_type", "ref_id"]))
    return getattr(result, "rowcount", 0) or 0


async def receipts_on(session: AsyncSession, site_id: uuid.UUID, start: datetime, end: datetime
                      ) -> list[tuple[datetime, uuid.UUID, Decimal]]:
    rows = await session.execute(select(StockMovement.at, StockMovement.ingredient_id, StockMovement.qty_base).where(
        StockMovement.site_id == site_id, StockMovement.type == "receipt",
        and_(StockMovement.at >= start, StockMovement.at < end)))
    return [(a, i, Decimal(q)) for a, i, q in rows.all()]

