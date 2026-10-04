"""Recommendation generators (FR-ACT-01/02, FR-PRC-07/10, FR-MNU-06).

An investigation's drafts name a type and a subject; each generator prices the draft from the site's own
data (usage, supplier offers, stock, recipe cost, volume) and returns a Recommendation in `draft` with its
formula, inputs, adjustable parameters, confidence, risk, approver role, expiry, follow-up date and success
metric. A draft that does not hold up against the data (no cheaper reliable supplier, GP already on
target) produces nothing.
"""

import math
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from statistics import pstdev
from typing import Any

from sqlalchemy import func, select

from app.core.tenancy.context import SiteContext
from app.domain.actions import impact as imp
from app.domain.actions.models import Recommendation
from app.domain.actions.rules import APPROVER, SUCCESS_METRIC
from app.domain.intelligence.models import Anomaly, Investigation, ItemCostSnapshot
from app.domain.inventory.models import Ingredient, SiteIngredient, StockMovement
from app.domain.inventory.services import current_wac, on_hand
from app.domain.menu.margin_engine import cost_at
from app.domain.menu.models import MenuItem
from app.domain.menu.repricing import suggest
from app.domain.pricing.supplier_ranking import rank_for_ingredient, switch_candidate
from app.domain.purchasing.models import Supplier, SupplierProduct

ZERO = Decimal(0)


def _q(v: Decimal, places: str = "0.01") -> float:
    return float(v.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def kg(qty_base: Decimal, base_unit: str) -> tuple[Decimal, str]:
    return (qty_base / 1000, "kg" if base_unit == "g" else "l") if base_unit in ("g", "ml") else (qty_base, base_unit)


async def generate(ctx: SiteContext, investigation: Investigation, anomaly: Anomaly, case_id: uuid.UUID
                   ) -> list[Recommendation]:
    causes = {c["cause_code"]: Decimal(str(c["confidence"])) for c in investigation.narrative.get("causes", [])}
    today = await ctx.today()
    out: list[Recommendation] = []
    seen: set[tuple[str, str]] = set()
    types = {d["type"] for d in investigation.draft_recommendations}
    for draft in investigation.draft_recommendations:
        key = (draft["type"], f"{draft['subject'].get('type')}:{draft['subject'].get('id')}")
        if key in seen:
            continue
        seen.add(key)
        fn = GENERATORS.get(draft["type"])
        if fn is None:
            continue
        rec = await fn(ctx, draft, investigation, anomaly, causes, today)
        if rec is None:
            continue
        rec.case_id = case_id
        out.append(rec)
    if "supplier_switch" not in {r.type for r in out} and "par_level_change" in types:
        ingredient = next((d["subject"]["id"] for d in investigation.draft_recommendations
                           if d["type"] == "par_level_change"), None)
        if ingredient and (po := await purchase_order(ctx, {"subject": {"type": "ingredient", "id": ingredient}},
                                                       investigation, anomaly, causes, today)) is not None:
            po.case_id = case_id
            out.append(po)
    return out


def _base(ctx: SiteContext, investigation: Investigation, anomaly: Anomaly, rec_type: str, subject: dict[str, Any],
          today: date, confidence: Decimal) -> Recommendation:
    return Recommendation(
        organisation_id=ctx.organisation_id, site_id=ctx.site_id, investigation_id=investigation.id, type=rec_type,
        subject=subject, status="draft", confidence=confidence.quantize(Decimal("0.0001")),
        required_role=APPROVER[rec_type], success_metric=SUCCESS_METRIC[rec_type],
        evidence_ref={"investigation_id": str(investigation.id), "anomaly_id": str(anomaly.id),
                      "node_ids": [n["id"] for n in investigation.graph.get("nodes", [])][:12]},
        expires_at=datetime.now(UTC) + timedelta(hours=ctx.config.get("actions.recommendation_expiry_hours")),
        follow_up_at=today + timedelta(days=ctx.config.get("actions.follow_up_days")), version=1,
    )


async def weekly_usage(ctx: SiteContext, ingredient_id: uuid.UUID, today: date) -> tuple[Decimal, list[Decimal]]:
    """Mean weekly theoretical usage over 28 days, and the daily series."""
    rows = dict((await ctx.session.execute(select(StockMovement.business_date, func.sum(-StockMovement.qty_base)).where(
        StockMovement.site_id == ctx.site_id, StockMovement.ingredient_id == ingredient_id,
        StockMovement.type == "theoretical_consumption",
        StockMovement.business_date.between(today - timedelta(days=27), today)).group_by(
        StockMovement.business_date))).all())
    series = [Decimal(rows.get(today - timedelta(days=i), 0)) for i in range(28)]
    return sum(series, ZERO) / 4, series


async def _default_product(ctx: SiteContext, ingredient_id: uuid.UUID) -> tuple[SiteIngredient, SupplierProduct | None]:
    si = (await ctx.session.execute(select(SiteIngredient).where(
        SiteIngredient.site_id == ctx.site_id, SiteIngredient.ingredient_id == ingredient_id))).scalar_one()
    product = (await ctx.session.execute(select(SupplierProduct).where(
        SupplierProduct.id == si.default_supplier_product_id))).scalar_one_or_none()
    return si, product


async def supplier_switch(ctx: SiteContext, draft: dict, inv: Investigation, anomaly: Anomaly,
                          causes: dict[str, Decimal], today: date) -> Recommendation | None:
    """FR-PRC-10: an alternative >= 5% cheaper with fill rate >= 95%; saving = weekly usage x price difference."""
    ingredient_id = uuid.UUID(draft["subject"]["id"])
    ing = (await ctx.session.execute(select(Ingredient).where(Ingredient.id == ingredient_id))).scalar_one()
    si, current = await _default_product(ctx, ingredient_id)
    if current is None:
        return None
    offers = await rank_for_ingredient(ctx.session, ctx.organisation_id, ctx.site_id, ingredient_id, as_of=today)
    cand = switch_candidate(offers, current.supplier_id,
                            min_saving_pct=Decimal(str(ctx.config.get("procurement.switch_min_saving_pct"))),
                            min_fill_rate=Decimal(str(ctx.config.get("procurement.switch_min_fill_rate"))))
    if cand is None:
        return None
    weekly, _ = await weekly_usage(ctx, ingredient_id, today)
    saving = imp.supplier_switch(weekly, cand.price_delta_per_base_minor)
    if saving <= 0:
        return None
    stock = (await on_hand(ctx.session, ctx.site_id, ingredient_ids=[ingredient_id])).get(ingredient_id, ZERO)
    po_qty = max(Decimal(si.par_level_base) - max(stock, ZERO), ZERO)
    w_qty, unit = kg(weekly, ing.base_unit)
    scale = Decimal(1000) if ing.base_unit in ("g", "ml") else Decimal(1)
    p_from = (cand.incumbent.price_per_base_minor or ZERO) * scale / 100  # major units per kg / l / each
    p_to = (cand.alternative.price_per_base_minor or ZERO) * scale / 100
    confidence = max((causes.get(c, ZERO) for c in ("supplier_short_delivery", "supplier_price_increase")), default=ZERO)
    rec = _base(ctx, inv, anomaly, "supplier_switch", {"type": "ingredient", "id": str(ingredient_id),
                                                      "name": ing.name}, today, confidence or inv.confidence)
    rec.expected_impact_minor = saving
    rec.risk = "medium"
    rec.impact_inputs = {
        "formula": imp.FORMULAS["supplier_switch"], "weekly_qty_base": float(weekly),
        "price_delta_per_base": float(cand.price_delta_per_base_minor), "weekly_qty": _q(w_qty, "1"), "unit": unit,
        "price_from": _q(p_from), "price_to": _q(p_to), "price_delta": _q(p_from - p_to),
        "saving_pct": _q(cand.saving_pct * 100, "0.1"), "fill_rate_pct": _q((cand.alternative.fill_rate or ZERO) * 100, "1"),
        "adjustable": ["po_qty_base"],
    }
    rec.parameters = {
        "title": f"Switch {ing.name.lower()} to {cand.alternative.supplier_name}",
        "ingredient_id": str(ingredient_id), "from_supplier_id": str(cand.incumbent.supplier_id),
        "from_supplier_name": cand.incumbent.supplier_name, "to_supplier_id": str(cand.alternative.supplier_id),
        "to_supplier_name": cand.alternative.supplier_name,
        "to_supplier_product_id": str(cand.alternative.supplier_product_id), "po_qty_base": float(po_qty),
    }
    rec.notes = (f"{cand.alternative.supplier_name} has delivered {rec.impact_inputs['fill_rate_pct']}% of ordered "
                 f"quantities over 90 days; the first order goes out on approval.")
    return rec


async def par_level_change(ctx: SiteContext, draft: dict, inv: Investigation, anomaly: Anomaly,
                           causes: dict[str, Decimal], today: date) -> Recommendation | None:
    """Order-up-to par = mean daily need x review period (the gap between the supplier's deliveries) + safety
    stock z x sigma x sqrt(L + R), sigma being the day-to-day error around the weekday means over 28 days with
    the stock-out day un-censored (lost need added back); impact = lost GP avoided - holding cost."""
    ingredient_id = uuid.UUID(draft["subject"]["id"])
    ing = (await ctx.session.execute(select(Ingredient).where(Ingredient.id == ingredient_id))).scalar_one()
    si, product = await _default_product(ctx, ingredient_id)
    supplier = (await ctx.session.execute(select(Supplier).where(Supplier.id == product.supplier_id))).scalar_one() \
        if product else None
    _, series = await weekly_usage(ctx, ingredient_id, today)
    stock_node = next((n for n in inv.graph.get("nodes", []) if n["id"] == "stock"), None)
    scale = Decimal(1000) if ing.base_unit in ("g", "ml") else Decimal(1)
    # Un-censor the stock-out day: what sold plus what could not be sold.
    lost_need = Decimal(str(stock_node["facts"].get("need_after", 0))) * scale if stock_node else ZERO
    by_day = {today - timedelta(days=i): q for i, q in enumerate(series)}
    by_day[today] = by_day.get(today, ZERO) + lost_need
    weekday_mean = {w: sum((q for d, q in by_day.items() if d.weekday() == w), ZERO) / 4 for w in range(7)}
    residuals = [float(q - weekday_mean[d.weekday()]) for d, q in by_day.items() if weekday_mean[d.weekday()] > 0]
    sigma = Decimal(str(pstdev(residuals))) if len(residuals) > 1 else ZERO
    mean_daily = sum(by_day.values(), ZERO) / len(by_day)
    lead = Decimal(supplier.lead_time_days if supplier else 1)
    days = sorted(supplier.delivery_weekdays) if supplier and supplier.delivery_weekdays else []
    review = Decimal(7) / len(days) if days else Decimal(ctx.config.get("procurement.review_period_days"))
    z = Decimal(str(ctx.config.get("procurement.service_level_z")))
    # Par (order-up-to) = mean need over the review period + safety stock z x sigma(forecast error) x sqrt(L + R).
    target = mean_daily * review + z * sigma * Decimal(str(math.sqrt(float(lead + review))))
    pack = product.base_qty_per_unit if product else Decimal(1)
    par_to = (target / pack).to_integral_value(rounding=ROUND_CEILING) * pack
    par_from = Decimal(si.par_level_base)
    if par_to <= par_from:
        return None
    wac = (await current_wac(ctx.session, ctx.site_id, ingredient_ids=[ingredient_id])).get(ingredient_id, ZERO)
    events = await _stock_out_events(ctx, ingredient_id, today)
    lost_gp = int(anomaly.facts.get("lost_gp_minor") or 0) or await _lost_gp(ctx, inv)
    per_week = Decimal(events) / 4
    value = imp.par_level_change(lost_gp, per_week, par_from, par_to, wac)
    f_from, unit = kg(par_from, ing.base_unit)
    f_to, _ = kg(par_to, ing.base_unit)
    rec = _base(ctx, inv, anomaly, "par_level_change", {"type": "ingredient", "id": str(ingredient_id),
                                                       "name": ing.name}, today,
                max(causes.get("stock_out", ZERO), causes.get("supplier_short_delivery", ZERO)) or inv.confidence)
    rec.expected_impact_minor = value
    rec.risk = "low"
    rec.impact_inputs = {
        "formula": imp.FORMULAS["par_level_change"], "lost_gp_per_event": lost_gp, "events_per_week": float(per_week),
        "stock_outs_28d": events, "par_from_base": float(par_from), "par_to_base": float(par_to),
        "wac_per_base": float(wac), "mean_daily_need": _q(mean_daily / scale), "sigma_daily": _q(sigma / scale),
        "lead_time_days": float(lead), "review_period_days": _q(review), "z": float(z), "unit": unit,
        "par_from": _q(f_from, "0.1"), "par_to": _q(f_to, "0.1"), "adjustable": ["par_level_base"],
    }
    rec.parameters = {"title": f"Raise {ing.name.lower()} par from {_q(f_from, '0.1'):g} to {_q(f_to, '0.1'):g} {unit}",
                      "ingredient_id": str(ingredient_id), "par_level_base": float(par_to)}
    return rec


async def _stock_out_events(ctx: SiteContext, ingredient_id: uuid.UUID, today: date) -> int:
    from app.domain.memory.models import MemoryEntry

    anomalies = int((await ctx.session.execute(select(func.count()).select_from(Anomaly).where(
        Anomaly.site_id == ctx.site_id, Anomaly.detector == "stock_out",
        Anomaly.subject["id"].astext == str(ingredient_id),
        Anomaly.period_end >= today - timedelta(days=28)))).scalar() or 0)
    remembered = int((await ctx.session.execute(select(func.count()).select_from(MemoryEntry).where(
        MemoryEntry.site_id == ctx.site_id, MemoryEntry.subject_keys.contains([f"ingredient:{ingredient_id}"]),
        MemoryEntry.cause_code.in_(("stock_out", "supplier_short_delivery")),
        MemoryEntry.occurred_on >= today - timedelta(days=28)))).scalar() or 0)
    return max(anomalies, 1) + remembered


async def _lost_gp(ctx: SiteContext, inv: Investigation) -> int:
    rows = (await ctx.session.execute(select(Anomaly.facts).where(
        Anomaly.site_id == ctx.site_id, Anomaly.detector == "stock_out",
        Anomaly.id.in_([uuid.UUID(a) for a in inv.graph.get("related_anomalies", [])])))).scalars().all()
    return max((int(f.get("lost_gp_minor") or 0) for f in rows), default=0)


async def price_review(ctx: SiteContext, draft: dict, inv: Investigation, anomaly: Anomaly,
                       causes: dict[str, Decimal], today: date) -> Recommendation | None:
    """FR-MNU-06: the price that restores the target GP %, rounded to the price endings; never applied
    automatically - the executor opens a review task for the Owner."""
    item_id = uuid.UUID(draft["subject"]["id"])
    item = (await ctx.session.execute(select(MenuItem).where(MenuItem.id == item_id))).scalar_one()
    cost = await cost_at(ctx, item_id, today)
    if cost.price_gross_minor is None or cost.vat_rate is None:
        return None
    target = Decimal(str(ctx.config.get("targets.gp_pct")))
    if cost.gp_pct is not None and cost.gp_pct >= target * 100:
        return None
    units = (await ctx.session.execute(select(func.coalesce(func.sum(ItemCostSnapshot.units_sold), 0)).where(
        ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.menu_item_id == item_id,
        ItemCostSnapshot.business_date.between(today - timedelta(days=27), today)))).scalar() or ZERO
    weekly_units = Decimal(units) / 4
    r = suggest(cost_minor=cost.cost_minor, current_gross_minor=cost.price_gross_minor, vat_rate=cost.vat_rate,
                target_gp=target, endings=ctx.config.get("menu.price_endings"), weekly_units=weekly_units)
    if r.suggested_gross_minor <= r.current_gross_minor:
        return None
    # The GP gap is measured exactly; the uncertainty is the demand response, hence 0.5 without a cause.
    rec = _base(ctx, inv, anomaly, "price_review", {"type": "menu_item", "id": str(item_id), "name": item.name},
                today, inv.confidence or Decimal("0.5"))
    rec.expected_impact_minor = r.weekly_gp_impact_minor
    rec.risk = "medium"
    rec.impact_inputs = {
        "formula": imp.FORMULAS["price_review"], "cost_minor": cost.cost_minor,
        "current_gross_minor": r.current_gross_minor, "vat_rate": float(cost.vat_rate),
        "weekly_units": _q(weekly_units, "0.1"), "current_gp_pct": float(r.current_gp_pct),
        "suggested_gp_pct": float(r.suggested_gp_pct), "target_gp_pct": float(r.target_gp_pct),
        "impact_lower_volume_minor": r.weekly_gp_impact_lower_volume_minor, "adjustable": ["suggested_gross_minor"],
    }
    rec.parameters = {"title": f"Review {item.name} price: {r.current_gross_minor / 100:.2f} → "
                               f"{r.suggested_gross_minor / 100:.2f}",
                      "menu_item_id": str(item_id), "suggested_gross_minor": r.suggested_gross_minor}
    rec.notes = "Prices are never changed automatically; approval opens a price review task for the Owner."
    return rec


async def purchase_order(ctx: SiteContext, draft: dict, inv: Investigation, anomaly: Anomaly,
                         causes: dict[str, Decimal], today: date) -> Recommendation | None:
    """FR-PRC-07: a draft PO for the next delivery when stock is below par (stock-out risk)."""
    ingredient_id = uuid.UUID(draft["subject"]["id"])
    ing = (await ctx.session.execute(select(Ingredient).where(Ingredient.id == ingredient_id))).scalar_one()
    si, product = await _default_product(ctx, ingredient_id)
    if product is None:
        return None
    stock = (await on_hand(ctx.session, ctx.site_id, ingredient_ids=[ingredient_id])).get(ingredient_id, ZERO)
    gap = Decimal(si.par_level_base) - max(stock, ZERO)
    if gap <= 0:
        return None
    rec = _base(ctx, inv, anomaly, "purchase_order", {"type": "ingredient", "id": str(ingredient_id), "name": ing.name},
                today, max(causes.values(), default=inv.confidence))
    rec.expected_impact_minor = await _lost_gp(ctx, inv)
    rec.risk = "low"
    rec.impact_inputs = {"formula": imp.FORMULAS["purchase_order"], "lost_gp_avoided_minor": rec.expected_impact_minor,
                         "on_hand_base": float(stock), "par_base": float(si.par_level_base), "adjustable": ["qty_base"]}
    rec.parameters = {"title": f"Order {ing.name.lower()} for the next delivery", "ingredient_id": str(ingredient_id),
                      "supplier_product_id": str(product.id), "qty_base": float(gap)}
    return rec


async def task(ctx: SiteContext, draft: dict, inv: Investigation, anomaly: Anomaly, causes: dict[str, Decimal],
               today: date) -> Recommendation | None:
    rec_type = draft["type"]
    rec = _base(ctx, inv, anomaly, rec_type, draft["subject"], today, inv.confidence)
    rec.expected_impact_minor = int(anomaly.weekly_impact_minor) if rec_type != "investigate_task" else 0
    rec.risk = "low"
    rec.impact_inputs = {"formula": imp.FORMULAS[rec_type], "impact_minor": rec.expected_impact_minor, "adjustable": []}
    rec.parameters = {"title": draft.get("reason") or rec_type.replace("_", " ").capitalize()}
    rec.follow_up_at = today + timedelta(days=ctx.config.get("actions.follow_up_days")) if rec_type != \
        "investigate_task" else None
    return rec


GENERATORS = {
    "supplier_switch": supplier_switch,
    "par_level_change": par_level_change,
    "price_review": price_review,
    "purchase_order": purchase_order,
    "investigate_task": task,
    "waste_reduction": task,
    "staffing_change": task,
}
