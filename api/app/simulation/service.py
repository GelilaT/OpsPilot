"""Simulate the next trading day for a site (FR-ING-02).

One transaction: supplier deliveries arrive (goods received, and booked into stock unless the invoice
is to be uploaded), the day's sales are pulled through the site's PosPort and ingested exactly like a
real POS, theoretical consumption is posted, waste and counts are logged, the kitchen places its next
orders and the site clock moves forward. The nightly pipeline for that date is enqueued by the caller.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select, update

from app.core.audit import record_audit
from app.core.errors import Conflict, Unprocessable
from app.core.tenancy.context import SiteContext
from app.core.tenancy.models import SiteClock
from app.domain.inventory.models import SiteIngredient, StockCount, StockCountLine, StockMovement, WasteEntry
from app.domain.inventory.rules import money_minor
from app.domain.inventory.services import post_theoretical_consumption
from app.domain.purchasing.invoice_models import Invoice, InvoiceLine
from app.domain.purchasing.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PriceObservation,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.domain.sales.models import WeatherDay
from app.domain.sales.services import ingest_day
from app.ports import IntegrationKind
from app.ports.errors import PortError
from app.simulation.catalogue import weather
from app.simulation.persist import count_rows, delivery_rows, po_rows, po_status_after, waste_row
from app.simulation.scenarios import PRICE_EVENTS, SCENARIO_CATALOGUE, SHORT_DELIVERIES
from app.simulation.state import SimTarget, load_world, org_slug, resolve_target

TABLES = {
    "goods_receipt": GoodsReceipt, "goods_receipt_line": GoodsReceiptLine, "invoice": Invoice,
    "invoice_line": InvoiceLine, "stock_movement": StockMovement, "price_observation": PriceObservation,
}


@dataclass
class DaySummary:
    business_date: str
    deliveries: list[dict] = field(default_factory=list)
    awaiting_invoice_upload: list[str] = field(default_factory=list)
    orders: int = 0
    revenue_ex_vat_minor: int = 0
    stock_outs: dict[str, str] = field(default_factory=dict)
    waste_entries: int = 0
    purchase_orders_placed: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)


def scenarios_on(slug: str, site_code: str, day) -> list[str]:
    active = []
    if any(e.org == slug and e.on == day for e in PRICE_EVENTS if e.supplier == "ASH"):
        active.append("S1")
    if any(s.org == slug and s.site == site_code and s.on == day for s in SHORT_DELIVERIES):
        active.append("S7" if day.month == 9 else "S2")
    return active


async def simulator_target(ctx: SiteContext) -> SimTarget:
    slug = await org_slug(ctx.session, ctx.organisation_id)
    code = None
    try:
        provider, settings, _, _ = await ctx.registry.connection_for(ctx.session, IntegrationKind.pos,
                                                                     ctx.organisation_id, ctx.site_id)
        if provider == "simulator":
            code = settings.get("site_code")
    except PortError:
        pass
    target = resolve_target(slug or "", code or "") if code else None
    if target is None:
        raise Conflict("This site is not connected to the simulator.", code="not_simulated")
    return target


async def simulate_next_day(ctx: SiteContext, scenario: str | None = None) -> DaySummary:
    if not ctx.config.get("simulation.enabled"):
        raise Conflict("Simulation is not enabled for this site.", code="simulation_disabled")
    target = await simulator_target(ctx)
    clock = (await ctx.session.execute(
        select(SiteClock).where(SiteClock.site_id == ctx.site_id).with_for_update())).scalar_one_or_none()
    if clock is None:
        raise Conflict("This site has no simulator clock.", code="not_simulated")
    day = clock.business_date + timedelta(days=1)
    planted = scenarios_on(target.profile.slug, target.site.code, day)
    if scenario and scenario not in planted:
        known = SCENARIO_CATALOGUE.get(scenario)
        raise Unprocessable(
            f"Scenario {scenario} is not planted on {day.isoformat()}." if known else f"Unknown scenario {scenario!r}.",
            code="scenario_not_available")
    cat = target.catalogue
    summary = DaySummary(day.isoformat(), scenarios=planted)
    world = await load_world(ctx.session, target, ctx.site_id, day)

    # Par level changes planted in the scenario calendar.
    for ingredient, old, new, reason in world.apply_par_changes(day):
        await ctx.session.execute(update(SiteIngredient).where(
            SiteIngredient.site_id == ctx.site_id, SiteIngredient.ingredient_id == cat.ingredient_ids[ingredient]
        ).values(par_level_base=new, version=SiteIngredient.version + 1))
        record_audit(ctx.session, actor="system:simulator", entity_type="site_ingredient", entity_id=ingredient,
                     action="par_level_change", organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                     before={"par_level_base": old}, after={"par_level_base": new, "reason": reason})

    # 1. Deliveries.
    for delivery in world.deliveries(day):
        rows = delivery_rows(ctx.organisation_id, ctx.site_id, cat, target.site, delivery, delivery.wac_after)
        for table, data in rows.items():
            if data:
                await ctx.session.execute(insert(TABLES[table]), data)
        if delivery.po_id:
            await ctx.session.execute(update(PurchaseOrder).where(PurchaseOrder.id == uuid.UUID(delivery.po_id)).values(
                status=po_status_after(delivery)))
        summary.deliveries.append({"supplier": cat.suppliers[delivery.supplier].name,
                                   "invoice_number": delivery.invoice_number, "po": delivery.po_number,
                                   "booked": not delivery.upload_only})
        if delivery.upload_only:
            posted = (await ctx.session.execute(select(Invoice).where(
                Invoice.purchase_order_id == uuid.UUID(delivery.po_id), Invoice.status == "posted"))).scalars().first() \
                if delivery.po_id else None
            if posted is not None:  # the invoice was uploaded and posted before the goods were recorded
                gr_id = rows["goods_receipt"][0]["id"]
                await ctx.session.execute(update(GoodsReceipt).where(GoodsReceipt.id == gr_id).values(
                    invoice_id=posted.id, invoice_number=posted.number))
                await ctx.session.execute(update(Invoice).where(Invoice.id == posted.id).values(goods_receipt_id=gr_id))
                summary.deliveries[-1]["booked"] = True
            else:
                summary.awaiting_invoice_upload.append(delivery.invoice_number)
    await ctx.session.flush()

    # 2. Sales through the PosPort, ingested exactly like a real POS.
    pos = await ctx.adapter(IntegrationKind.pos)
    result = await ingest_day(ctx, day, pos)
    summary.orders, summary.revenue_ex_vat_minor = result.orders, result.revenue_ex_vat_minor
    sales = await pos.fetch_sales(day)
    _, tracker = world.sales(day, *_view_from(world))
    summary.stock_outs = {ing: at.strftime("%H:%M") for ing, at in tracker.stock_out_at.items()}

    # 3. Close of day: theoretical consumption from the ingested sales (FR-STK-03), waste and counts.
    close = datetime.combine(day, target.site.closing, tzinfo=ctx.tz) + timedelta(minutes=50)
    await post_theoretical_consumption(ctx, day, close)
    eod = world.end_of_day(day, sales)
    for m in eod.movements:
        if m.type == "theoretical_consumption":
            continue  # posted above from the database
        await ctx.session.execute(insert(StockMovement).values(
            organisation_id=ctx.organisation_id, site_id=ctx.site_id, ingredient_id=cat.ingredient_ids[m.ingredient],
            at=m.at, business_date=day, type=m.type, qty_base=m.qty_base, unit_cost_minor=m.unit_cost_minor,
            cost_minor=money_minor(m.qty_base, m.unit_cost_minor), ref_type=m.ref_type, ref_id=m.ref_id))
    if eod.waste:
        await ctx.session.execute(insert(WasteEntry), [waste_row(ctx.organisation_id, ctx.site_id, cat, w, day)
                                                       for w in eod.waste])
    summary.waste_entries = len(eod.waste)
    if eod.count:
        header, lines = count_rows(ctx.organisation_id, ctx.site_id, cat, eod.count, day)
        await ctx.session.execute(insert(StockCount).values(**header))
        await ctx.session.execute(insert(StockCountLine), lines)

    # 4. The kitchen orders for the coming deliveries.
    for po in world.place_orders(day):
        header, lines = po_rows(ctx.organisation_id, ctx.site_id, cat, po, ctx.currency)
        await ctx.session.execute(insert(PurchaseOrder).values(**header))
        await ctx.session.execute(insert(PurchaseOrderLine), lines)
        summary.purchase_orders_placed.append(po.number)

    # 5. Weather for the day (WeatherPort; degraded mode falls back to the recorded fixture).
    await _store_weather(ctx, target, day)

    clock.business_date = day
    clock.updated_at = datetime.now(UTC)
    record_audit(ctx.session, actor=ctx.actor, entity_type="site_clock", entity_id=ctx.site_id,
                 action="simulate_next_day", organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                 after={"business_date": day.isoformat(), "orders": summary.orders, "scenarios": planted,
                        "awaiting_invoice_upload": summary.awaiting_invoice_upload})
    return summary


def _view_from(world):
    """Opening stock and today's receipts as the world saw them before service (for stock-out timing)."""
    opening = {k: v - sum(q for _, i, q in world.state.receipts_today if i == k) for k, v in world.state.on_hand.items()}
    return opening, list(world.state.receipts_today)


async def _store_weather(ctx: SiteContext, target: SimTarget, day) -> None:
    exists = (await ctx.session.execute(select(WeatherDay.id).where(
        WeatherDay.site_id == ctx.site_id, WeatherDay.day == day))).first()
    if exists:
        return
    w = weather(target.site.city, day)
    try:
        port = await ctx.adapter(IntegrationKind.weather)
        rows = await port.history(ctx.site.latitude, ctx.site.longitude, day, day, ctx.site.timezone)
        if rows:
            r = rows[0]
            w = type(w)(r.temp_max_c, r.temp_min_c, r.precipitation_mm, r.source)
    except PortError:
        pass  # degraded mode: recorded/climatology weather
    await ctx.session.execute(insert(WeatherDay).values(
        id=uuid.uuid4(), organisation_id=ctx.organisation_id, site_id=ctx.site_id, day=day, temp_max_c=w.temp_max,
        temp_min_c=w.temp_min, precipitation_mm=w.precipitation, source=w.source))

