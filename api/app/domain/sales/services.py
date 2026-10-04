"""Sales and labour ingestion through the PosPort (FR-ING-02/04/06)."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.integrations import ExternalRef
from app.core.tenancy.context import SiteContext
from app.domain.sales.models import CashUp, SalesOrder, SalesOrderLine, Shift
from app.ports import IntegrationKind
from app.ports.pos import CanonicalCashUp, CanonicalSale, CanonicalShift, PosPort


@dataclass(frozen=True)
class DaypartWindow:
    name: str
    start: time
    end: time


def dayparts_from_config(value: list[Any]) -> list[DaypartWindow]:
    return [DaypartWindow(d.name, d.start, d.end) if hasattr(d, "name") else
            DaypartWindow(d["name"], time.fromisoformat(d["start"]), time.fromisoformat(d["end"])) for d in value]


def daypart_for(at: datetime, tz: ZoneInfo, windows: list[DaypartWindow]) -> str:
    local = at.astimezone(tz).time()
    for w in windows:
        if w.start <= local < w.end:
            return w.name
    if windows and local < windows[0].start:
        return windows[0].name
    return windows[-1].name if windows else "dinner"


def ex_vat(gross_minor: int, vat_rate: Decimal) -> int:
    return int((Decimal(gross_minor) / (1 + vat_rate)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def sale_rows(sale: CanonicalSale, *, organisation_id: uuid.UUID, site_id: uuid.UUID, tz: ZoneInfo,
              dayparts: list[DaypartWindow], item_ids: dict[str, uuid.UUID]) -> tuple[dict, list[dict]]:
    """Map one canonical sale to sales_order / sales_order_line rows (shared by ingestion and the seed)."""
    order_id = uuid.uuid4()
    daypart = daypart_for(sale.opened_at, tz, dayparts)
    lines, gross, discount, void, net, revenue = [], 0, 0, 0, 0, 0
    for line in sale.lines:
        menu_item_id = item_ids.get(line.external_item_id)
        if menu_item_id is None:
            raise KeyError(f"Unmapped POS item {line.external_item_id!r}")
        line_gross = int(line.quantity * line.unit_price_minor)
        line_net = line_gross - line.discount_minor
        line_rev = ex_vat(line_net, line.vat_rate)
        gross += line_gross
        discount += line.discount_minor
        void += int(line.void_quantity * line.unit_price_minor)
        net += line_net
        revenue += line_rev
        lines.append({
            "id": uuid.uuid4(), "organisation_id": organisation_id, "site_id": site_id, "order_id": order_id,
            "menu_item_id": menu_item_id, "business_date": sale.business_date, "sold_at": sale.opened_at,
            "daypart": daypart, "quantity": line.quantity, "void_quantity": line.void_quantity,
            "void_reason": line.void_reason, "unit_price_minor": line.unit_price_minor, "vat_rate": line.vat_rate,
            "discount_minor": line.discount_minor, "net_minor": line_net, "revenue_ex_vat_minor": line_rev,
        })
    order = {
        "id": order_id, "organisation_id": organisation_id, "site_id": site_id,
        "external_order_id": sale.external_order_id, "business_date": sale.business_date,
        "opened_at": sale.opened_at, "closed_at": sale.closed_at, "daypart": daypart, "covers": sale.covers,
        "channel": sale.channel, "currency": sale.currency, "gross_minor": gross, "discount_minor": discount,
        "void_minor": void, "net_minor": net, "vat_minor": net - revenue, "revenue_ex_vat_minor": revenue,
        "discount_reason": sale.discount_reason,
    }
    return order, lines


def shift_row(shift: CanonicalShift, *, organisation_id: uuid.UUID, site_id: uuid.UUID) -> dict:
    hours = Decimal(str(round((shift.ends_at - shift.starts_at).total_seconds() / 3600, 2)))
    return {
        "id": uuid.uuid4(), "organisation_id": organisation_id, "site_id": site_id,
        "external_shift_id": shift.external_shift_id, "business_date": shift.business_date,
        "staff_ref": shift.staff_ref, "staff_display_name": shift.staff_display_name, "role": shift.role,
        "starts_at": shift.starts_at, "ends_at": shift.ends_at, "hours": hours,
        "hourly_rate_minor": shift.hourly_rate_minor,
        "cost_minor": int((hours * shift.hourly_rate_minor).quantize(Decimal(1), rounding=ROUND_HALF_UP)),
    }


def cash_up_row(c: CanonicalCashUp, *, organisation_id: uuid.UUID, site_id: uuid.UUID) -> dict:
    return {"id": uuid.uuid4(), "organisation_id": organisation_id, "site_id": site_id,
            "business_date": c.business_date, "expected_cash_minor": c.expected_cash_minor,
            "counted_cash_minor": c.counted_cash_minor, "card_total_minor": c.card_total_minor,
            "variance_minor": c.counted_cash_minor - c.expected_cash_minor}


async def pos_item_map(session: AsyncSession, provider: str) -> dict[str, uuid.UUID]:
    rows = await session.execute(select(ExternalRef.external_id, ExternalRef.entity_id).where(
        ExternalRef.provider == provider, ExternalRef.entity_type == "menu_item"))
    return {ext: eid for ext, eid in rows.all()}


@dataclass
class IngestResult:
    business_date: date
    orders: int
    new_orders: int
    shifts: int
    cash_ups: int
    revenue_ex_vat_minor: int


async def ingest_day(ctx: SiteContext, day: date, pos: PosPort | None = None) -> IngestResult:
    """Pull one trading day from the site's POS and store it idempotently on (site, external_order_id)."""
    if pos is None:
        pos = await ctx.adapter(IntegrationKind.pos)
    assert pos is not None
    items = await pos_item_map(ctx.session, pos.provider)
    dayparts = dayparts_from_config(ctx.config.get("site.dayparts"))
    sales = await pos.fetch_sales(day)
    shifts = await pos.fetch_shifts(day)
    cash_ups = await pos.fetch_cash_ups(day)

    new_orders = 0
    revenue = 0
    for sale in sales:
        order, lines = sale_rows(sale, organisation_id=ctx.organisation_id, site_id=ctx.site_id, tz=ctx.tz,
                                 dayparts=dayparts, item_ids=items)
        inserted = (await ctx.session.execute(
            insert(SalesOrder).values(**order).on_conflict_do_nothing(
                index_elements=["site_id", "external_order_id"]).returning(SalesOrder.id))).scalar_one_or_none()
        if inserted is not None:
            new_orders += 1
            revenue += order["revenue_ex_vat_minor"]
            if lines:
                await ctx.session.execute(insert(SalesOrderLine), lines)
    for shift in shifts:
        await ctx.session.execute(insert(Shift).values(**shift_row(
            shift, organisation_id=ctx.organisation_id, site_id=ctx.site_id)).on_conflict_do_nothing(
            index_elements=["site_id", "external_shift_id"]))
    for cash_up in cash_ups:
        await ctx.session.execute(insert(CashUp).values(**cash_up_row(
            cash_up, organisation_id=ctx.organisation_id, site_id=ctx.site_id)).on_conflict_do_nothing(
            index_elements=["site_id", "business_date"]))
    record_audit(ctx.session, actor=ctx.actor, entity_type="sales_day", entity_id=f"{ctx.site_id}:{day}",
                 action="ingest", organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                 after={"provider": pos.provider, "orders": len(sales), "new_orders": new_orders,
                        "shifts": len(shifts), "cash_ups": len(cash_ups)})
    return IngestResult(day, len(sales), new_orders, len(shifts), len(cash_ups), revenue)
