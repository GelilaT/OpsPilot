"""Hypothesis Library (SRS S10): deterministic tests that join data across domains (FR-RCA-03/04).

Each test returns evidence nodes with computed facts, a verdict (supports / refutes / neutral) for one
cause code, its supporting evidence as (weight, strength) pairs, the largest refuting weight and a timing
factor (1 when the cause precedes the effect inside the window, otherwise 0.5). The engine combines them:

    confidence(cause) = (1 - prod(1 - w_k * s_k)) * timing * (1 - max_refuting_weight)

Weights are part of the library (calibrated on the seeded scenarios and documented in the design).
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any, Literal

from sqlalchemy import func, select

from app.core.tenancy.context import SiteContext
from app.domain.detectors.baseline import Baseline
from app.domain.detectors.data import DayFacts
from app.domain.detectors.stock_out import StockOutEvent, find_stock_outs
from app.domain.inventory.models import Ingredient
from app.domain.menu.models import MenuItemPrice
from app.domain.purchasing.invoice_models import Invoice, InvoiceLine
from app.domain.purchasing.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PriceObservation,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.domain.sales.models import WeatherDay

ZERO = Decimal(0)
ONE = Decimal(1)
Verdict = Literal["supports", "refutes", "neutral"]

# Weights of the library (w_k). Strengths (s_k) are computed facts in 0..1.
W = {
    "short_vs_order": Decimal("0.70"),  # received/invoiced short of the PO by > 10%
    "short_caused_stock_out": Decimal("0.60"),  # the missing quantity would have covered the lost need
    "stock_out_explains_drop": Decimal("0.75"),  # dishes needing the ingredient explain the spend change
    "price_explains_cost": Decimal("0.90"),  # ingredient price change explains the item cost change
    "menu_price_change": Decimal("0.70"),
    "weather": Decimal("0.60"),
    "leakage": Decimal("0.80"),
    "staffing": Decimal("0.60"),
    "cash": Decimal("0.85"),
    "demand": Decimal("0.50"),
    "similar_case": Decimal("0.35"),
    "enough_stock_refutes": Decimal("0.60"),
}


def clip(v: Decimal) -> Decimal:
    return max(ZERO, min(ONE, v)).quantize(Decimal("0.0001"))


def r2(v: Decimal | float | int) -> float:
    return float(Decimal(str(v)).quantize(Decimal("0.01")))


def major(minor: int | Decimal) -> float:
    return r2(Decimal(minor) / 100)


@dataclass
class Result:
    test: str
    cause_code: str
    verdict: Verdict
    nodes: list[dict[str, Any]] = field(default_factory=list)
    supporting: list[tuple[Decimal, Decimal]] = field(default_factory=list)
    refuting: Decimal = ZERO
    timing: Decimal = ONE
    summary: str = ""
    entities: set[str] = field(default_factory=set)
    chain: list[str] = field(default_factory=list)


@dataclass
class HContext:
    """What the hypotheses see: the anomaly window, baselines, driver tree and the entities involved."""

    ctx: SiteContext
    family: str
    day: date
    baseline_days: list[date]
    days: dict[date, DayFacts]
    focus_items: dict[uuid.UUID, str] = field(default_factory=dict)  # dishes driving the change
    focus_ingredients: set[uuid.UUID] = field(default_factory=set)
    focus_share: Decimal = ZERO  # share of the change explained by the focus items (0..1)
    effect_start: datetime | None = None  # when the effect began (concentrated segment start)
    effect_end: datetime | None = None
    item_cost_drivers: list[Any] = field(default_factory=list)  # ItemDriver rows for margin anomalies
    anomaly_facts: dict[str, Any] = field(default_factory=dict)
    stock_outs: list[StockOutEvent] = field(default_factory=list)
    results: list[Result] = field(default_factory=list)

    @property
    def today(self) -> DayFacts:
        return self.days[self.day]

    def baseline(self, fn) -> Baseline:
        return Baseline.of([Decimal(fn(self.days[d])) for d in self.baseline_days if self.days[d].traded])


Test = Callable[[HContext], Awaitable[Result | None]]
LIBRARY: dict[str, tuple[set[str], Test]] = {}


def hypothesis(name: str, families: set[str]) -> Callable[[Test], Test]:
    def wrap(fn: Test) -> Test:
        LIBRARY[name] = (families, fn)
        return fn
    return wrap


REVENUE, MARGIN, SUPPLY, LEAKAGE, LABOUR = "revenue", "margin", "supply", "leakage", "labour"


@hypothesis("ingredient_stock_out", {REVENUE, SUPPLY})
async def ingredient_stock_out(h: HContext) -> Result | None:
    events = h.stock_outs
    if h.focus_ingredients:
        events = [e for e in events if e.ingredient_id in h.focus_ingredients] or events
    if not events:
        return Result("ingredient_stock_out", "stock_out", "refutes", summary="No ingredient ran out during service.")
    e = max(events, key=lambda ev: sum(ev.lost_units.values()))
    scale = Decimal(1000) if e.base_unit in ("g", "ml") else ONE
    unit = {"g": "kg", "ml": "l"}.get(e.base_unit, e.base_unit)
    strength = h.focus_share if h.focus_share > 0 else Decimal("0.5")
    precedes = h.effect_end is None or e.out_at <= h.effect_end
    node = {"id": "stock", "kind": "stock", "label": f"{e.ingredient_name} on hand",
            "facts": {"ingredient": e.ingredient_name, "on_hand": r2(e.on_hand_left / scale), "unit": unit,
                      "out_at": e.out_at.strftime("%H:%M"),
                      "need_after": r2(e.need_after_qty / scale), "opening": r2(e.opening_qty / scale),
                      "received": r2(e.received_qty / scale), "sold_after": r2(e.sold_after_qty / scale),
                      "dishes": len(e.dependent_items)}}
    return Result("ingredient_stock_out", "stock_out", "supports", [node],
                  [(W["stock_out_explains_drop"], clip(strength))], timing=ONE if precedes else Decimal("0.5"),
                  summary=(f"{e.ingredient_name} on hand was 0 {unit} at {node['facts']['out_at']}; the evening needed "
                           f"{node['facts']['need_after']} {unit}."),
                  entities={f"ingredient:{e.ingredient_id}"})


def _dec(v: object) -> Decimal | None:
    return None if v is None else Decimal(str(v))


@dataclass(frozen=True)
class Delivery:
    po_number: str
    supplier_id: uuid.UUID
    supplier_name: str
    ingredient_id: uuid.UUID
    ordered: Decimal
    received: Decimal
    invoiced: Decimal | None
    invoice_number: str | None
    unit_price_minor: Decimal | None
    price_per_base_minor: Decimal | None
    received_at: datetime | None


async def deliveries(ctx: SiteContext, start: date, end: date, ingredient_ids: set[uuid.UUID]) -> list[Delivery]:
    """PO lines due in the window joined to goods received and invoice lines (three-way)."""
    if not ingredient_ids:
        return []
    rows = (await ctx.session.execute(select(
        PurchaseOrder.id, PurchaseOrder.number, PurchaseOrder.supplier_id, Supplier.name, PurchaseOrderLine.id,
        PurchaseOrderLine.ingredient_id, PurchaseOrderLine.qty_base,
    ).join(PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id).join(
        Supplier, Supplier.id == PurchaseOrder.supplier_id).where(
        PurchaseOrder.site_id == ctx.site_id, PurchaseOrder.expected_delivery_date.between(start, end),
        PurchaseOrderLine.ingredient_id.in_(ingredient_ids),
        PurchaseOrder.status.in_(("committed", "sent", "part_received", "received"))))).all()
    out = []
    for po_id, number, sup_id, sup_name, line_id, ing, ordered in rows:
        got_qty, received_at = (await ctx.session.execute(select(
            func.coalesce(func.sum(GoodsReceiptLine.qty_base), 0), func.min(GoodsReceipt.received_at)).join(
            GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.goods_receipt_id).where(
            GoodsReceiptLine.purchase_order_line_id == line_id))).one()
        inv = (await ctx.session.execute(select(Invoice.number, func.sum(InvoiceLine.qty_base),
                                                func.max(InvoiceLine.unit_price_minor),
                                                func.max(InvoiceLine.price_per_base_minor)).join(
            InvoiceLine, InvoiceLine.invoice_id == Invoice.id).where(
            Invoice.purchase_order_id == po_id, InvoiceLine.ingredient_id == ing,
            Invoice.status.in_(("approved", "posted"))).group_by(Invoice.number))).first()
        inv_number, inv_qty, inv_price, inv_ppb = inv if inv else (None, None, None, None)
        out.append(Delivery(number, sup_id, sup_name, ing, Decimal(ordered), Decimal(got_qty),
                            _dec(inv_qty), inv_number, _dec(inv_price), _dec(inv_ppb), received_at))
    return out


async def median_price_90d(ctx: SiteContext, ingredient_id: uuid.UUID, supplier_id: uuid.UUID, before: date
                           ) -> Decimal | None:
    rows = (await ctx.session.execute(select(PriceObservation.price_per_base_minor).where(
        PriceObservation.site_id == ctx.site_id, PriceObservation.ingredient_id == ingredient_id,
        PriceObservation.supplier_id == supplier_id,
        PriceObservation.observed_on.between(before - timedelta(days=90), before - timedelta(days=1))))).scalars().all()
    return Decimal(str(median([Decimal(r) for r in rows]))) if rows else None


def received_qty(d: Delivery) -> Decimal:
    """Three-way: the smaller of goods received and invoiced; an invoice posted before the goods were
    recorded stands in for the goods receipt."""
    if d.invoiced is None:
        return d.received
    return d.invoiced if d.received == 0 else min(d.received, d.invoiced)


@hypothesis("supplier_short_delivery", {REVENUE, SUPPLY})
async def supplier_short_delivery(h: HContext) -> Result | None:
    targets = {e.ingredient_id for e in h.stock_outs} & h.focus_ingredients or h.focus_ingredients or {
        e.ingredient_id for e in h.stock_outs}
    rows = await deliveries(h.ctx, h.day - timedelta(days=3), h.day, targets)
    shorts = []
    for d in rows:
        got = received_qty(d)
        gap = (d.ordered - got) / d.ordered if d.ordered else ZERO
        if gap > Decimal("0.10"):
            shorts.append((gap, d, got))
    if not shorts:
        return Result("supplier_short_delivery", "supplier_short_delivery", "refutes",
                      summary="Deliveries in the window matched their purchase orders.")
    gap, d, got = max(shorts, key=lambda s: s[0])
    names = {i: (n, u) for i, n, u in (await h.ctx.session.execute(select(Ingredient.id, Ingredient.name,
                                                                          Ingredient.base_unit).where(
        Ingredient.id == d.ingredient_id))).all()}
    ing_name, base_unit = names[d.ingredient_id]
    scale = Decimal(1000) if base_unit in ("g", "ml") else ONE
    unit = {"g": "kg", "ml": "l"}.get(base_unit, base_unit)
    facts: dict[str, Any] = {
        "po_number": d.po_number, "supplier": d.supplier_name, "ingredient": ing_name, "unit": unit,
        "ordered": r2(d.ordered / scale), "received": r2(d.received / scale),
        "invoiced": r2(d.invoiced / scale) if d.invoiced is not None else None, "invoice_number": d.invoice_number,
        "short_pct": r2(gap * 100), "median_window_days": 90,
    }
    if d.price_per_base_minor is not None:
        med = await median_price_90d(h.ctx, d.ingredient_id, d.supplier_id, h.day)
        facts["price"] = major(d.price_per_base_minor * scale)
        if med:
            facts["median_price_90d"] = major(med * scale)
            facts["price_change_pct"] = r2((d.price_per_base_minor - med) / med * 100)
    supporting = [(W["short_vs_order"], clip(gap / Decimal("0.40")))]
    nodes = [{"id": "purchasing", "kind": "purchasing", "label": f"{d.po_number} from {d.supplier_name}", "facts": facts}]
    chain = ["supplier_short_delivery"]
    refuting = ZERO
    timing = ONE
    event = next((e for e in h.stock_outs if e.ingredient_id == d.ingredient_id), None)
    if event is not None:
        missing = d.ordered - got
        link = clip(missing / event.need_after_qty) if event.need_after_qty > 0 else ONE
        supporting.append((W["short_caused_stock_out"], link))
        chain.append("stock_out")
        nodes.append({"id": "link", "kind": "link", "label": "Short delivery → stock-out",
                      "facts": {"missing": r2(missing / scale), "need_after": r2(event.need_after_qty / scale),
                                "unit": unit, "out_at": event.out_at.strftime("%H:%M")}})
        if d.received_at is not None and d.received_at > event.out_at:
            timing = Decimal("0.5")
    elif got >= d.ordered:
        refuting = W["enough_stock_refutes"]
    return Result("supplier_short_delivery", "supplier_short_delivery", "supports", nodes, supporting, refuting, timing,
                  summary=(f"{d.po_number} from {d.supplier_name}: {facts['received']} {unit} received against "
                           f"{facts['ordered']} {unit} ordered."),
                  entities={f"supplier:{d.supplier_id}", f"ingredient:{d.ingredient_id}"}, chain=chain)


@hypothesis("supplier_price_increase", {MARGIN, REVENUE})
async def supplier_price_increase(h: HContext) -> Result | None:
    drivers = [d for d in h.item_cost_drivers if d.delta_minor > 0]
    if h.family == REVENUE:
        return None  # an ingredient price affects margin, not sales, unless the menu price moved (tested below)
    if not drivers:
        return Result("supplier_price_increase", "supplier_price_increase", "refutes",
                      summary="No ingredient cost increase behind the change.")
    top = drivers[0]
    # Strength: the share of the cost change this ingredient explains, scaled by how material the change is
    # (a 5% item cost rise or more counts fully).
    base = int(h.anomaly_facts.get("item_cost_from_minor") or sum(d.cost_from_minor for d in h.item_cost_drivers))
    rise = Decimal(top.cost_to_minor - top.cost_from_minor) / Decimal(max(base, 1))
    share = Decimal(str(top.pct_of_change)) / 100 * clip(rise / Decimal("0.05"))
    node = {"id": "cost", "kind": "cost", "label": f"{top.ingredient_name} cost",
            "facts": {"ingredient": top.ingredient_name, "supplier": top.supplier_name,
                      "cost_from": major(top.cost_from_minor), "cost_to": major(top.cost_to_minor),
                      "share_pct": r2(top.pct_of_change)}}
    entities = {f"ingredient:{top.ingredient_id}"} | ({f"supplier:{top.supplier_id}"} if top.supplier_id else set())
    return Result("supplier_price_increase", "supplier_price_increase", "supports", [node],
                  [(W["price_explains_cost"], clip(share))],
                  summary=f"{top.ingredient_name} explains {r2(top.pct_of_change)}% of the cost change.", entities=entities)


@hypothesis("menu_price_change", {REVENUE, MARGIN})
async def menu_price_change(h: HContext) -> Result | None:
    if not h.focus_items:
        return None
    rows = (await h.ctx.session.execute(select(MenuItemPrice.menu_item_id, MenuItemPrice.effective_from).where(
        MenuItemPrice.site_id == h.ctx.site_id, MenuItemPrice.menu_item_id.in_(list(h.focus_items)),
        MenuItemPrice.effective_from.between(h.day - timedelta(days=7), h.day)))).all()
    if not rows:
        return Result("menu_price_change", "menu_price_change", "refutes",
                      summary="No menu price changed in or just before the window.")
    node = {"id": "menu_price", "kind": "menu", "label": "Menu price change",
            "facts": {"items": len(rows), "changed_on": min(r[1] for r in rows).isoformat()}}
    return Result("menu_price_change", "menu_price_change", "supports", [node], [(W["menu_price_change"], ONE)],
                  summary="A menu price changed just before the window.")


def weather_factor(temp_max: Decimal, rain_mm: Decimal) -> Decimal:
    """Multiplicative demand factor of a day's weather (MVP rule table; FCT-03 fits these in v2.x)."""
    f = ONE
    if rain_mm > 15:
        f *= Decimal("0.88")
    elif rain_mm > 5:
        f *= Decimal("0.94")
    if temp_max >= 23:
        f *= Decimal("1.08")
    elif temp_max < 10:
        f *= Decimal("0.95")
    return f.quantize(Decimal("0.01"))


@hypothesis("weather_effect", {REVENUE})
async def weather_effect(h: HContext) -> Result | None:
    w = (await h.ctx.session.execute(select(WeatherDay).where(
        WeatherDay.site_id == h.ctx.site_id, WeatherDay.day == h.day))).scalar_one_or_none()
    if w is None:
        return None
    f = weather_factor(Decimal(w.temp_max_c), Decimal(w.precipitation_mm))
    node = {"id": "weather", "kind": "weather", "label": "Weather",
            "facts": {"factor": r2(f), "temp_max_c": r2(w.temp_max_c), "rain_mm": r2(w.precipitation_mm)}}
    if Decimal("0.9") <= f <= Decimal("1.1"):
        return Result("weather_effect", "weather", "refutes", [node], summary=f"Weather normal (factor {r2(f):.2f}).")
    return Result("weather_effect", "weather", "supports", [node], [(W["weather"], clip(abs(ONE - f) / Decimal("0.2")))],
                  summary=f"Weather factor {r2(f):.2f}.")


@hypothesis("discount_or_void_spike", {REVENUE, LEAKAGE})
async def discount_or_void_spike(h: HContext) -> Result | None:
    t = h.today
    b = h.baseline(lambda f: f.rate(f.discount + f.void) * 100)
    if b.n < 3:
        return None
    rate = t.rate(t.discount + t.void) * 100
    node = {"id": "leakage", "kind": "leakage", "label": "Discounts and voids",
            "facts": {"rate_pct": r2(rate), "baseline_pct": r2(b.median), "limit_pct": r2(b.median + 2 * b.sigma)}}
    if rate <= b.median + 2 * b.sigma:
        return Result("discount_or_void_spike", "discount_abuse", "refutes", [node],
                      summary=f"Discounts and voids {r2(rate):.1f}% vs {r2(b.median):.1f}% baseline.")
    strength = clip((rate - b.median) / (4 * b.sigma)) if b.sigma else ONE
    return Result("discount_or_void_spike", "discount_abuse", "supports", [node], [(W["leakage"], strength)],
                  summary=f"Discounts and voids {r2(rate):.1f}% vs {r2(b.median):.1f}% baseline.")


@hypothesis("staffing_shortfall", {REVENUE, LABOUR})
async def staffing_shortfall(h: HContext) -> Result | None:
    t = h.today
    if not t.labour_hours:
        return None
    b = h.baseline(lambda f: Decimal(f.covers) / f.labour_hours if f.labour_hours else 0)
    if b.n < 3:
        return None
    cph = Decimal(t.covers) / t.labour_hours
    node = {"id": "staffing", "kind": "labour", "label": "Covers per labour hour",
            "facts": {"covers_per_hour": r2(cph), "baseline": r2(b.median), "labour_hours": r2(t.labour_hours)}}
    if cph <= b.median + 2 * b.sigma:
        return Result("staffing_shortfall", "staffing_shortfall", "refutes", [node],
                      summary=f"Covers per labour hour {r2(cph):.1f} vs {r2(b.median):.1f}.")
    return Result("staffing_shortfall", "staffing_shortfall", "supports", [node],
                  [(W["staffing"], clip((cph - b.median) / (4 * b.sigma)) if b.sigma else ONE)],
                  summary=f"Covers per labour hour {r2(cph):.1f} vs {r2(b.median):.1f}.")


@hypothesis("cash_handling", {LEAKAGE})
async def cash_handling(h: HContext) -> Result | None:
    var = h.today.cash_variance
    if var is None:
        return None
    limit = h.ctx.config.get("detection.cash_variance_minor")
    node = {"id": "cash", "kind": "cash", "label": "Cash-up", "facts": {"variance": major(var), "limit": major(limit)}}
    if abs(var) <= limit:
        return Result("cash_handling", "cash_handling", "refutes", [node], summary="Cash-up within tolerance.")
    return Result("cash_handling", "cash_handling", "supports", [node],
                  [(W["cash"], clip(Decimal(abs(var)) / (2 * limit)))], summary=f"Cash-up variance {major(var):.2f}.")


@hypothesis("demand_shift", {REVENUE})
async def demand_shift(h: HContext) -> Result | None:
    values = [Decimal(h.days[d].orders) for d in h.baseline_days if h.days[d].traded]
    if len(values) < 3:
        return None
    lo, hi = min(values), max(values)  # p10..p90 of the baseline orders
    orders = Decimal(h.today.orders)
    med = Decimal(str(median(values)))
    node = {"id": "demand", "kind": "demand", "label": "Orders", "facts": {
        "orders": int(orders), "baseline": r2(med), "low": int(lo), "high": int(hi),
        "change_pct": r2((orders - med) / med * 100) if med else 0}}
    others = any(r.verdict == "supports" and r.cause_code not in ("demand_shift",) for r in h.results)
    if lo <= orders <= hi or others:
        return Result("demand_shift", "demand_shift", "refutes" if lo <= orders <= hi else "neutral", [node],
                      summary="Orders within the normal range." if lo <= orders <= hi else "Orders moved with another cause.")
    return Result("demand_shift", "demand_shift", "supports", [node],
                  [(W["demand"], clip(abs(orders - med) / med / Decimal("0.2")) if med else ONE)],
                  summary="Orders outside the normal range with no other cause.")


async def load_stock_outs(h: HContext) -> None:
    h.stock_outs = await find_stock_outs(h.ctx, h.day, [d for d in h.baseline_days if h.days[d].traded])
