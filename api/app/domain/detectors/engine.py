"""Nightly detector registry and anomaly persistence (FR-ANO-01..06, FR-PRC-02, FR-MNU-05).

Detectors are deterministic functions of one site and business date. The registry runs the v1 rules
(AR-01 discount spike, AR-02 void spike, AR-03 labour over target, AR-04 daypart revenue drop, AR-05/06
product decline/surge, AR-07 cash-up variance, AR-08 COGS drift, AR-09 revenue drop) and the v2 detectors
(price_increase, stock_out, margin_decline, supplier_fill_rate, plus the FR-MNU-05 menu checks). Baselines
are same-weekday median/MAD over `detection.baseline_weeks`; with fewer than
`detection.min_baseline_points` points a detector is skipped and the skip is logged.

Each anomaly has a fingerprint (detector + subject + episode start). A detection that continues an open
episode (same detector and subject, previous occurrence within the detector's gap) increases its streak
instead of creating a duplicate; re-running the same date is idempotent. Severity comes from the weekly
money impact (info < warning threshold <= warning < critical threshold <= critical).
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.tenancy.context import SiteContext
from app.domain.detectors.baseline import Baseline, same_weekdays
from app.domain.detectors.data import DayFacts, load_days
from app.domain.detectors.stock_out import find_stock_outs
from app.domain.intelligence.models import Anomaly, ItemCostSnapshot
from app.domain.inventory.models import Ingredient, StockMovement
from app.domain.menu.models import MenuItem
from app.domain.pricing.supplier_ranking import fill_rates
from app.domain.purchasing.models import PriceObservation, Supplier

log = logging.getLogger("opspilot.detectors")
ZERO = Decimal(0)
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def q2(v: Decimal | float) -> float:
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def pct(observed: Decimal | int, expected: Decimal | int) -> float:
    e = Decimal(expected)
    return q2((Decimal(observed) - e) / e * 100) if e else 0.0


@dataclass(frozen=True)
class Detection:
    detector: str
    subject: dict[str, Any]  # {"type", "id", "name", ...}
    period_start: date
    period_end: date
    weekly_impact_minor: int
    facts: dict[str, Any]
    rule: str | None = None
    gap_days: int = 1  # an occurrence within this many days continues the episode
    max_severity: str | None = None  # v1 rules whose table severity is fixed (AR-05/06: info)


@dataclass
class DetectionRun:
    day: date
    days: dict[date, DayFacts]
    baseline_days: list[date]
    skipped: list[str] = field(default_factory=list)

    @property
    def today(self) -> DayFacts:
        return self.days[self.day]

    def baseline(self, fn: Callable[[DayFacts], Decimal | int | None]) -> list[Decimal]:
        values = []
        for d in self.baseline_days:
            f = self.days[d]
            if not f.traded:
                continue
            v = fn(f)
            if v is not None:
                values.append(Decimal(v))
        return values


def subject_key(subject: dict[str, Any]) -> str:
    return f"{subject['type']}:{subject['id']}"


def fingerprint(detector: str, subject: dict[str, Any], episode_start: date) -> str:
    payload = json.dumps({"d": detector, "s": subject_key(subject), "a": episode_start.isoformat()}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def severity_for(weekly_impact_minor: int, cfg) -> str:
    if weekly_impact_minor >= cfg.get("detection.severity_critical_minor"):
        return "critical"
    if weekly_impact_minor >= cfg.get("detection.severity_warning_minor"):
        return "warning"
    return "info"


Detector = Callable[[SiteContext, DetectionRun], Awaitable[list[Detection]]]
REGISTRY: dict[str, Detector] = {}


def detector(name: str) -> Callable[[Detector], Detector]:
    def wrap(fn: Detector) -> Detector:
        REGISTRY[name] = fn
        return fn
    return wrap


def _enough(ctx: SiteContext, run: DetectionRun, name: str, values: list[Decimal]) -> bool:
    if len(values) < ctx.config.get("detection.min_baseline_points"):
        run.skipped.append(name)
        log.info("detector skipped: insufficient baseline", extra={"detector": name, "points": len(values),
                                                                    "site_id": str(ctx.site_id)})
        return False
    return True


def _site(ctx: SiteContext) -> dict[str, Any]:
    return {"type": "site", "id": str(ctx.site_id), "name": ctx.site.name}


def _baseline_facts(run: DetectionRun, b: Baseline) -> dict[str, Any]:
    return {"baseline_dates": [d.isoformat() for d in run.baseline_days if run.days[d].traded],
            "baseline_values": [int(v) for v in b.values], "baseline_n": b.n}


# --------------------------------------------------------------------------------------------------
# v1 rules
# --------------------------------------------------------------------------------------------------
@detector("revenue_day")
async def revenue_day(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """AR-09: net revenue below baseline by `detection.revenue_drop_pct`."""
    t = run.today
    values = run.baseline(lambda f: f.revenue)
    if not t.traded or not _enough(ctx, run, "revenue_day", values):
        return []
    b = Baseline.of(values)
    drop = Decimal(str(ctx.config.get("detection.revenue_drop_pct")))
    if Decimal(t.revenue) >= b.median * (1 - drop):
        return []
    shortfall = int(b.median) - t.revenue
    dp_base = {dp: Baseline.of(run.baseline(lambda f, dp=dp: f.daypart_revenue.get(dp, 0))).median
               for dp in set(t.daypart_revenue) | {dp for d in run.baseline_days for dp in run.days[d].daypart_revenue}}
    by_dp = {dp: int(t.daypart_revenue.get(dp, 0) - m) for dp, m in dp_base.items()}
    worst = min(by_dp, key=lambda k: by_dp[k]) if by_dp else None
    return [Detection("revenue_day", _site(ctx), run.day, run.day, shortfall, {
        "metric": "revenue_ex_vat_minor", "observed": t.revenue, "expected": int(b.median),
        "deviation_pct": pct(t.revenue, b.median), "robust_z": q2(b.z(Decimal(t.revenue)) or 0),
        "shortfall_minor": shortfall, "dimension": f"daypart:{worst}" if worst else None,
        "daypart_delta_minor": by_dp, **_baseline_facts(run, b),
    }, rule="AR-09")]


@detector("daypart_revenue")
async def daypart_revenue(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """AR-04: a daypart's revenue below baseline by `detection.daypart_drop_pct`."""
    t = run.today
    if not t.traded:
        return []
    drop = Decimal(str(ctx.config.get("detection.daypart_drop_pct")))
    out = []
    for dp in sorted({dp for d in run.baseline_days for dp in run.days[d].daypart_revenue}):
        values = run.baseline(lambda f, dp=dp: f.daypart_revenue.get(dp, 0))
        if not _enough(ctx, run, f"daypart_revenue:{dp}", values):
            continue
        b = Baseline.of(values)
        observed = t.daypart_revenue.get(dp, 0)
        if b.median <= 0 or Decimal(observed) >= b.median * (1 - drop):
            continue
        shortfall = int(b.median) - observed
        out.append(Detection("daypart_revenue", {"type": "daypart", "id": f"{ctx.site_id}:{dp}", "name": dp},
                             run.day, run.day, shortfall, {
                                 "metric": "daypart_revenue_ex_vat_minor", "daypart": dp, "observed": observed,
                                 "expected": int(b.median), "deviation_pct": pct(observed, b.median),
                                 "shortfall_minor": shortfall, **_baseline_facts(run, b)}, rule="AR-04"))
    return out


@detector("discount_spike")
async def discount_spike(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """AR-01: discount rate above max(tolerance, baseline + 2 sigma)."""
    t = run.today
    values = run.baseline(lambda f: f.rate(f.discount))
    if not t.traded or not _enough(ctx, run, "discount_spike", values):
        return []
    b = Baseline.of(values)
    limit = max(Decimal(str(ctx.config.get("detection.discount_tolerance_pct"))), b.median + 2 * b.sigma)
    rate = t.rate(t.discount)
    if rate <= limit:
        return []
    excess = int((rate - b.median) * t.gross)
    return [Detection("discount_spike", _site(ctx), run.day, run.day, excess, {
        "metric": "discount_rate", "observed": q2(rate * 100), "expected": q2(b.median * 100),
        "limit": q2(limit * 100), "discount_minor": t.discount, "excess_minor": excess}, rule="AR-01")]


@detector("void_spike")
async def void_spike(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """AR-02: void rate above baseline + 2 sigma and void value at least `detection.void_min_minor`."""
    t = run.today
    values = run.baseline(lambda f: f.rate(f.void))
    if not t.traded or not _enough(ctx, run, "void_spike", values):
        return []
    b = Baseline.of(values)
    rate = t.rate(t.void)
    if rate <= b.median + 2 * b.sigma or t.void < ctx.config.get("detection.void_min_minor"):
        return []
    excess = int((rate - b.median) * t.gross)
    return [Detection("void_spike", _site(ctx), run.day, run.day, excess, {
        "metric": "void_rate", "observed": q2(rate * 100), "expected": q2(b.median * 100),
        "void_minor": t.void, "excess_minor": excess}, rule="AR-02")]


@detector("labour_over_target")
async def labour_over_target(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """AR-03: labour % above target + `detection.labour_over_points`."""
    t = run.today
    if not t.traded or t.revenue <= 0 or t.labour_cost <= 0:
        return []
    labour_pct = Decimal(t.labour_cost) / Decimal(t.revenue) * 100
    target = Decimal(str(ctx.config.get("targets.labour_pct"))) * 100
    over = labour_pct - target
    if over < Decimal(str(ctx.config.get("detection.labour_over_points"))):
        return []
    excess = int(over / 100 * t.revenue)
    return [Detection("labour_over_target", _site(ctx), run.day, run.day, excess, {
        "metric": "labour_pct", "observed": q2(labour_pct), "expected": q2(target), "over_points": q2(over),
        "labour_cost_minor": t.labour_cost, "labour_hours": q2(t.labour_hours),
        "covers_per_labour_hour": q2(Decimal(t.covers) / t.labour_hours) if t.labour_hours else None,
        "critical_rule": over >= Decimal(str(ctx.config.get("detection.labour_over_critical_points")))}, rule="AR-03")]


@detector("product_volume")
async def product_volume(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """AR-05 product decline (< 70% of baseline) and AR-06 surge (> 150%), baseline >= 10 units/day."""
    t = run.today
    if not t.traded:
        return []
    min_units = Decimal(ctx.config.get("detection.product_min_baseline_units"))
    decline = Decimal(str(ctx.config.get("detection.product_decline_ratio")))
    surge = Decimal(str(ctx.config.get("detection.product_surge_ratio")))
    items = {i for d in run.baseline_days for i in run.days[d].item_units}
    if not items:
        return []
    cm = await _latest_cm(ctx, run.day, list(items))
    names = {i: n for i, n in (await ctx.session.execute(select(MenuItem.id, MenuItem.name).where(
        MenuItem.id.in_(items)))).all()}
    out = []
    for item in items:
        values = run.baseline(lambda f, item=item: f.item_units.get(item, ZERO))
        if len(values) < ctx.config.get("detection.min_baseline_points"):
            continue
        b = Baseline.of(values)
        if b.median < min_units:
            continue
        units = t.item_units.get(item, ZERO)
        ratio = units / b.median
        if decline <= ratio <= surge:
            continue
        kind = "product_decline" if ratio < decline else "product_surge"
        impact = int(abs(b.median - units) * cm.get(item, 0))
        out.append(Detection(kind, {"type": "menu_item", "id": str(item), "name": names.get(item, "?")},
                             run.day, run.day, impact if kind == "product_decline" else 0, {
                                 "metric": "units", "observed": q2(units), "expected": q2(b.median),
                                 "ratio": q2(ratio), "cm_minor": cm.get(item, 0)},
                             rule="AR-05" if kind == "product_decline" else "AR-06", max_severity="info"))
    return out


@detector("cash_variance")
async def cash_variance(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """AR-07: |cash-up variance| above `detection.cash_variance_minor`."""
    var = run.today.cash_variance
    if var is None or abs(var) <= ctx.config.get("detection.cash_variance_minor"):
        return []
    return [Detection("cash_variance", _site(ctx), run.day, run.day, abs(var), {
        "metric": "cash_variance_minor", "observed": var, "expected": 0,
        "critical_rule": abs(var) > ctx.config.get("detection.cash_variance_critical_minor")}, rule="AR-07")]


@detector("cogs_drift")
async def cogs_drift(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """AR-08: COGS % above baseline + `detection.cogs_drift_points`."""
    t = run.today
    values = run.baseline(lambda f: Decimal(f.cogs) / f.revenue * 100 if f.revenue and f.cogs else None)
    if not t.traded or not t.cogs or not _enough(ctx, run, "cogs_drift", values):
        return []
    b = Baseline.of(values)
    cogs_pct = Decimal(t.cogs) / Decimal(t.revenue) * 100
    if cogs_pct - b.median < Decimal(str(ctx.config.get("detection.cogs_drift_points"))):
        return []
    excess = int((cogs_pct - b.median) / 100 * t.revenue)
    return [Detection("cogs_drift", _site(ctx), run.day, run.day, excess, {
        "metric": "cogs_pct", "observed": q2(cogs_pct), "expected": q2(b.median), "excess_minor": excess},
                      rule="AR-08")]


# --------------------------------------------------------------------------------------------------
# v2 detectors
# --------------------------------------------------------------------------------------------------
async def _weekly_usage(ctx: SiteContext, day: date, ingredient_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Mean weekly theoretical usage over the last 28 days."""
    rows = (await ctx.session.execute(select(StockMovement.ingredient_id, func.sum(-StockMovement.qty_base)).where(
        StockMovement.site_id == ctx.site_id, StockMovement.type == "theoretical_consumption",
        StockMovement.ingredient_id.in_(ingredient_ids),
        StockMovement.business_date.between(day - timedelta(days=27), day)).group_by(
        StockMovement.ingredient_id))).all()
    return {i: Decimal(q) / 4 for i, q in rows}


async def _wac_on(ctx: SiteContext, ingredient_ids: list[uuid.UUID], day: date) -> dict[uuid.UUID, Decimal]:
    from app.domain.menu.margin_engine import end_of_day

    at = end_of_day(ctx, day)
    sub = select(StockMovement.ingredient_id, StockMovement.unit_cost_minor, func.row_number().over(
        partition_by=StockMovement.ingredient_id, order_by=(StockMovement.at.desc(), StockMovement.id.desc())).label("rn")
    ).where(StockMovement.site_id == ctx.site_id, StockMovement.ingredient_id.in_(ingredient_ids),
            StockMovement.at < at, StockMovement.type.in_(("opening", "receipt"))).subquery()
    return {i: Decimal(c) for i, c in (await ctx.session.execute(
        select(sub.c.ingredient_id, sub.c.unit_cost_minor).where(sub.c.rn == 1))).all()}


@detector("price_increase")
async def price_increase(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """FR-PRC-02: weighted cost per base unit up >= 5% over 30 days, or latest price robust z >= 3 (90 days)."""
    day = run.day
    ids = list((await ctx.session.execute(select(StockMovement.ingredient_id).where(
        StockMovement.site_id == ctx.site_id, StockMovement.type == "receipt",
        StockMovement.business_date.between(day - timedelta(days=30), day)).distinct())).scalars())
    if not ids:
        return []
    now, before = await _wac_on(ctx, ids, day), await _wac_on(ctx, ids, day - timedelta(days=30))
    threshold = Decimal(str(ctx.config.get("detection.cost_increase_pct_30d")))
    z_limit = Decimal(str(ctx.config.get("detection.price_robust_z")))
    usage = await _weekly_usage(ctx, day, ids)
    obs: dict[uuid.UUID, list[tuple[date, Decimal, uuid.UUID]]] = {}
    for ing, on, price, sup in (await ctx.session.execute(select(
        PriceObservation.ingredient_id, PriceObservation.observed_on, PriceObservation.price_per_base_minor,
        PriceObservation.supplier_id).where(
        PriceObservation.site_id == ctx.site_id, PriceObservation.ingredient_id.in_(ids),
        PriceObservation.observed_on.between(day - timedelta(days=90), day)).order_by(
        PriceObservation.observed_on))).all():
        obs.setdefault(ing, []).append((on, Decimal(price), sup))
    meta = {i: (c, n, u) for i, c, n, u in (await ctx.session.execute(select(
        Ingredient.id, Ingredient.code, Ingredient.name, Ingredient.base_unit).where(Ingredient.id.in_(ids)))).all()}
    suppliers = {i: n for i, n in (await ctx.session.execute(select(Supplier.id, Supplier.name).where(
        Supplier.organisation_id == ctx.organisation_id))).all()}
    out = []
    for ing in ids:
        p1, p0 = now.get(ing), before.get(ing)
        series = obs.get(ing, [])
        z = None
        if len(series) >= 3:
            b = Baseline.of([p for _, p, _ in series[:-1]] or [series[-1][1]])
            z = b.z(series[-1][1])
        rise = (p1 - p0) / p0 if p1 is not None and p0 else ZERO
        if rise < threshold and (z is None or z < z_limit):
            continue
        weekly_qty = usage.get(ing, ZERO)
        impact = int(((p1 or ZERO) - (p0 or ZERO)) * weekly_qty) if p0 else 0
        code, name, unit = meta[ing]
        last = series[-1] if series else None
        out.append(Detection("price_increase", {"type": "ingredient", "id": str(ing), "name": name, "code": code},
                             day - timedelta(days=30), day, max(impact, 0), {
                                 "metric": "wac_per_base_minor", "base_unit": unit,
                                 "observed": q2(p1 or 0), "expected": q2(p0 or 0), "rise_pct": q2(rise * 100),
                                 "robust_z": q2(z) if z is not None else None, "weekly_qty_base": q2(weekly_qty),
                                 "latest_supplier": suppliers.get(last[2]) if last else None,
                                 "latest_supplier_id": str(last[2]) if last else None}, gap_days=1))
    return out


@detector("stock_out")
async def stock_out(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """On-hand reached zero while dependent items were on sale; impact = lost contribution."""
    if not run.today.traded:
        return []
    days = [d for d in run.baseline_days if run.days[d].traded]
    events = await find_stock_outs(ctx, run.day, days)
    if not events:
        return []
    cm = await _latest_cm(ctx, run.day, list({i for e in events for i in e.dependent_items}))
    out = []
    for e in events:
        lost_gp = int(sum((u * cm.get(i, 0) for i, u in e.lost_units.items()), ZERO))
        out.append(Detection("stock_out", {"type": "ingredient", "id": str(e.ingredient_id), "name": e.ingredient_name,
                                           "code": e.ingredient_code}, run.day, run.day, lost_gp, stock_out_facts(e, cm)))
    return out


def stock_out_facts(e, cm: dict[uuid.UUID, int]) -> dict[str, Any]:
    kg = e.base_unit in ("g", "ml")
    scale = Decimal(1000) if kg else Decimal(1)
    return {
        "metric": "on_hand", "out_at": e.out_at.strftime("%H:%M"), "on_hand": q2(e.on_hand_left / scale),
        "unit": ("kg" if e.base_unit == "g" else "l") if kg else e.base_unit,
        "opening": q2(e.opening_qty / scale), "received": q2(e.received_qty / scale),
        "need_after": q2(e.need_after_qty / scale), "sold_after": q2(e.sold_after_qty / scale),
        "lost_units": {str(i): q2(u) for i, u in e.lost_units.items()},
        "lost_gp_minor": int(sum((u * cm.get(i, 0) for i, u in e.lost_units.items()), ZERO)),
        "dependent_items": {str(i): n for i, n in e.dependent_items.items()},
    }


async def _latest_cm(ctx: SiteContext, day: date, items: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = (await ctx.session.execute(select(ItemCostSnapshot.menu_item_id, ItemCostSnapshot.cm_minor).where(
        ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.menu_item_id.in_(items),
        ItemCostSnapshot.business_date == (select(func.max(ItemCostSnapshot.business_date)).where(
            ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.business_date <= day).scalar_subquery())))).all()
    return {i: int(c) for i, c in rows}


async def _item_names(ctx: SiteContext) -> dict[uuid.UUID, str]:
    return {i: n for i, n in (await ctx.session.execute(select(MenuItem.id, MenuItem.name).where(
        MenuItem.organisation_id == ctx.organisation_id))).all()}


async def _snapshots(ctx: SiteContext, start: date, end: date) -> dict[uuid.UUID, list[ItemCostSnapshot]]:
    out: dict[uuid.UUID, list[ItemCostSnapshot]] = {}
    for s in (await ctx.session.execute(select(ItemCostSnapshot).where(
            ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.business_date.between(start, end)).order_by(
            ItemCostSnapshot.business_date))).scalars():
        out.setdefault(s.menu_item_id, []).append(s)
    return out


@detector("margin_decline")
async def margin_decline(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """FR-MNU-05: GP % down >= 3 points over 28 days on high-volume items."""
    start = run.day - timedelta(days=28)
    snaps = await _snapshots(ctx, start, run.day)
    threshold = Decimal(str(ctx.config.get("detection.margin_decline_points")))
    high_volume = Decimal(ctx.config.get("detection.high_volume_units_per_week"))
    names = {i: n for i, n in (await ctx.session.execute(select(MenuItem.id, MenuItem.name).where(
        MenuItem.organisation_id == ctx.organisation_id))).all()}
    out = []
    for item, rows in snaps.items():
        if len(rows) < 2 or rows[0].business_date != start or rows[-1].business_date != run.day:
            continue
        weekly_units = sum((Decimal(r.units_sold) for r in rows[-28:]), ZERO) / 4
        if weekly_units < high_volume:
            continue
        a, b = rows[0], rows[-1]
        drop = Decimal(a.gp_pct) - Decimal(b.gp_pct)
        if drop < threshold:
            continue
        impact = int((a.cm_minor - b.cm_minor) * weekly_units)
        out.append(Detection("margin_decline", {"type": "menu_item", "id": str(item), "name": names.get(item, "?")},
                             start, run.day, max(impact, 0), {
                                 "metric": "gp_pct", "observed": q2(b.gp_pct), "expected": q2(a.gp_pct),
                                 "gp_from": q2(a.gp_pct), "gp_to": q2(b.gp_pct), "drop_points": q2(drop),
                                 "cost_from_minor": a.cost_minor, "cost_to_minor": b.cost_minor,
                                 "price_ex_vat_minor": b.price_ex_vat_minor, "weekly_units": q2(weekly_units),
                                 "date_from": start.isoformat(), "date_to": run.day.isoformat()}))
    return out


@detector("item_cost_increase")
async def item_cost_increase(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """FR-MNU-05: item cost up >= 8% over 90 days (attribution is attached by the investigation)."""
    names = await _item_names(ctx)
    start = run.day - timedelta(days=90)
    first = {s.menu_item_id: s for s in (await ctx.session.execute(select(ItemCostSnapshot).where(
        ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.business_date == start))).scalars()}
    last = {s.menu_item_id: s for s in (await ctx.session.execute(select(ItemCostSnapshot).where(
        ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.business_date == run.day))).scalars()}
    threshold = Decimal(str(ctx.config.get("detection.item_cost_increase_pct_90d")))
    out = []
    for item, b in last.items():
        a = first.get(item)
        if a is None or a.cost_minor <= 0:
            continue
        rise = Decimal(b.cost_minor - a.cost_minor) / a.cost_minor
        if rise < threshold:
            continue
        weekly_units = Decimal(b.units_sold) * 7
        out.append(Detection("item_cost_increase", {"type": "menu_item", "id": str(item), "name": names.get(item, "?")}, start,
                             run.day,
                             int((b.cost_minor - a.cost_minor) * weekly_units), {
                                 "metric": "item_cost_minor", "observed": b.cost_minor, "expected": a.cost_minor,
                                 "rise_pct": q2(rise * 100)}))
    return out


@detector("item_food_cost_high")
async def item_food_cost_high(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """FR-MNU-05: ingredient cost % above target food cost + 5 points."""
    names = await _item_names(ctx)
    target = Decimal(str(ctx.config.get("targets.food_cost_pct"))) * 100
    over = Decimal(str(ctx.config.get("detection.food_cost_over_points")))
    out = []
    for s in (await ctx.session.execute(select(ItemCostSnapshot).where(
            ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.business_date == run.day))).scalars():
        if s.price_ex_vat_minor <= 0:
            continue
        food_pct = Decimal(s.cost_minor) / s.price_ex_vat_minor * 100
        if food_pct < target + over:
            continue
        excess = int((food_pct - target) / 100 * s.price_ex_vat_minor * Decimal(s.units_sold) * 7)
        out.append(Detection("item_food_cost_high", {"type": "menu_item", "id": str(s.menu_item_id),
                                                     "name": names.get(s.menu_item_id, "?")}, run.day,
                             run.day, excess, {"metric": "food_cost_pct", "observed": q2(food_pct),
                                               "expected": q2(target)}, gap_days=1))
    return out


@detector("menu_puzzle")
async def menu_puzzle(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """FR-MNU-05: high-margin, low-sales items over the last 28 days (info; promotion candidates)."""
    names = await _item_names(ctx)
    snaps = await _snapshots(ctx, run.day - timedelta(days=27), run.day)
    if not snaps:
        return []
    units = {i: sum((Decimal(r.units_sold) for r in rows), ZERO) for i, rows in snaps.items()}
    cms = {i: Decimal(rows[-1].cm_minor) for i, rows in snaps.items()}
    total_units = sum(units.values(), ZERO)
    if total_units <= 0:
        return []
    popularity = Decimal(1) / len(units) * Decimal("0.7")
    avg_cm = sum((cms[i] * units[i] for i in units), ZERO) / total_units
    if run.day.weekday() != 0:  # weekly (Mondays): the matrix moves slowly
        return []
    return [Detection("menu_puzzle", {"type": "menu_item", "id": str(i), "name": names.get(i, "?")},
                      run.day - timedelta(days=27), run.day, 0, {
        "metric": "menu_class", "class": "puzzle", "units_28d": q2(units[i]), "cm_minor": int(cms[i]),
        "avg_cm_minor": q2(avg_cm), "share_pct": q2(units[i] / total_units * 100)}, gap_days=7)
        for i in units if units[i] / total_units < popularity and cms[i] > avg_cm]


@detector("supplier_fill_rate")
async def supplier_fill_rate(ctx: SiteContext, run: DetectionRun) -> list[Detection]:
    """Received / ordered below `detection.supplier_min_fill_rate` over 30 days."""
    start = run.day - timedelta(days=30)
    rates = await fill_rates(ctx.session, ctx.site_id, start, run.day)
    floor = Decimal(str(ctx.config.get("detection.supplier_min_fill_rate")))
    names = {i: n for i, n in (await ctx.session.execute(select(Supplier.id, Supplier.name).where(
        Supplier.organisation_id == ctx.organisation_id))).all()}
    out = []
    for supplier_id, r in rates.items():
        if r.rate >= floor or r.lines < 3:
            continue
        weekly_value = Decimal(r.ordered_value_minor) / 30 * 7
        out.append(Detection("supplier_fill_rate", {"type": "supplier", "id": str(supplier_id),
                                                    "name": names.get(supplier_id, "?")}, start, run.day,
                             int((1 - r.rate) * weekly_value), {
                                 "metric": "fill_rate", "observed": q2(r.rate * 100), "expected": q2(floor * 100),
                                 "lines": r.lines, "short_lines": r.short_lines}))
    return out


# --------------------------------------------------------------------------------------------------
# Running and persisting
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Saved:
    anomaly: Anomaly
    new: bool
    escalated: bool


async def run_detectors(ctx: SiteContext, day: date, *, only: set[str] | None = None) -> list[Saved]:
    weeks = ctx.config.get("detection.baseline_weeks")
    baseline_days = same_weekdays(day, weeks)
    days = await load_days(ctx.session, ctx.site_id, [day, *baseline_days])
    run = DetectionRun(day, days, baseline_days)
    detections: list[Detection] = []
    for name, fn in REGISTRY.items():
        if only and name not in only:
            continue
        detections.extend(await fn(ctx, run))
    return [s for d in detections if (s := await save(ctx, d)) is not None]


async def save(ctx: SiteContext, det: Detection) -> Saved | None:
    severity = severity_for(det.weekly_impact_minor, ctx.config)
    if det.max_severity and SEVERITY_RANK[severity] > SEVERITY_RANK[det.max_severity]:
        severity = det.max_severity
    key = subject_key(det.subject)
    facts = {**det.facts, "rule": det.rule, "subject_key": key}
    candidates = (await ctx.session.execute(select(Anomaly).where(
        Anomaly.site_id == ctx.site_id, Anomaly.detector == det.detector,
        Anomaly.subject["type"].astext == det.subject["type"], Anomaly.subject["id"].astext == str(det.subject["id"]),
        Anomaly.period_end >= det.period_end - timedelta(days=det.gap_days),
    ).order_by(Anomaly.period_end.desc()).limit(1).with_for_update())).scalar_one_or_none()
    if candidates is not None and candidates.status == "dismissed":
        if candidates.dismissed_until and candidates.dismissed_until >= det.period_end:
            return None  # FR-ANO-06: dismissed as expected, suppressed
        candidates = None
    if candidates is not None and candidates.status != "closed":
        a = candidates
        before = a.severity
        if det.period_end > a.period_end:
            a.streak += 1
            a.period_end = det.period_end
        a.facts = facts
        a.weekly_impact_minor = det.weekly_impact_minor
        a.severity = severity
        escalated = SEVERITY_RANK[severity] > SEVERITY_RANK[a.investigated_severity or before]
        return Saved(a, False, escalated)
    a = Anomaly(
        organisation_id=ctx.organisation_id, site_id=ctx.site_id, detector=det.detector, subject=det.subject,
        period_start=det.period_start, period_end=det.period_end,
        fingerprint=fingerprint(det.detector, det.subject, det.period_start), severity=severity, facts=facts,
        weekly_impact_minor=det.weekly_impact_minor, status="open",
    )
    ctx.session.add(a)
    await ctx.session.flush()
    return Saved(a, True, False)


def investigable(s: Saved) -> bool:
    """FR-ANO-05: warning/critical start an investigation when new or escalated; info goes to the brief."""
    return s.anomaly.severity in ("warning", "critical") and s.anomaly.parent_id is None and (
        s.new or s.escalated or s.anomaly.investigated_severity is None)


__all__ = ["REGISTRY", "Detection", "Saved", "investigable", "run_detectors", "severity_for", "stock_out_facts"]
