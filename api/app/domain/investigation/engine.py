"""Root-cause investigation engine (FR-RCA-01..08).

1. Context: the anomaly, the metric's driver tree, the window, comparable baseline windows (the same
   weekday over the baseline weeks) and the entities involved.
2. Driver decomposition (revenue): LMDI orders x spend, spend split into mix and price effects and item
   contributions, grouped by shared ingredient; day x daypart segments, concentrated when one holds >= 60%.
   Margin anomalies decompose the item cost change by ingredient and supplier.
3. Hypothesis tests (Hypothesis Library) join menu, recipes, the stock ledger, POs, goods received,
   invoices, suppliers, weather, discounts, labour and cash-ups.
4. Confidence per cause, causes below the configured minimum hidden; similar past cases recalled from
   memory add evidence to the cause they share.
5. Output: finding, ordered evidence chain with computed facts, ranked causes, recommendation drafts,
   similar past cases, and a narrative (Gemini, Number Guard checked, deterministic template fallback).
Investigations are versioned: a re-run creates version n+1 and keeps the earlier ones.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.tenancy.context import SiteContext
from app.domain.detectors.baseline import same_weekdays
from app.domain.detectors.data import load_days
from app.domain.intelligence.models import Anomaly, Investigation, ItemCostSnapshot
from app.domain.investigation.confidence import cause_confidence
from app.domain.investigation.hypotheses import (
    LIBRARY,
    MARGIN,
    REVENUE,
    HContext,
    Result,
    W,
    clip,
    load_stock_outs,
    major,
    r2,
)
from app.domain.investigation.number_guard import check_narrative
from app.domain.memory.service import Recall, retrieve
from app.domain.menu.lmdi import concentration, decompose_revenue, split_spend
from app.domain.menu.models import MenuItem
from app.domain.pricing.attribution import item_attribution
from app.domain.sales.models import SalesOrderLine
from app.ports import IntegrationKind
from app.ports.ai import InvestigationNarrative

log = logging.getLogger("opspilot.investigation")
ZERO = Decimal(0)

FAMILY = {
    "revenue_day": REVENUE, "daypart_revenue": REVENUE, "product_decline": REVENUE,
    "margin_decline": MARGIN, "item_cost_increase": MARGIN, "item_food_cost_high": MARGIN, "price_increase": MARGIN,
    "cogs_drift": MARGIN, "stock_out": "supply", "supplier_fill_rate": "supply",
    "discount_spike": "leakage", "void_spike": "leakage", "cash_variance": "leakage", "labour_over_target": "labour",
}
CAUSE_LABEL = {
    "supplier_short_delivery": "Supplier short delivery", "stock_out": "Ingredient stock-out",
    "supplier_price_increase": "Supplier price increase", "menu_price_change": "Menu price change",
    "weather": "Weather", "discount_abuse": "Discounts and voids", "staffing_shortfall": "Staffing shortfall",
    "cash_handling": "Cash handling", "demand_shift": "Demand shift", "over_portioning": "Over-portioning",
    "waste_spike": "Waste spike",
}
NEXT_ACTION = {
    "supplier_short_delivery": "Approve the supplier and par level changes in the Action Centre.",
    "stock_out": "Raise the par level and check tomorrow's order.",
    "supplier_price_increase": "Review the supplier comparison and the dish prices.",
    "menu_price_change": "Review the price change against sales.",
    "discount_abuse": "Review discounts and voids with the shift managers.",
    "staffing_shortfall": "Review the rota for this daypart.",
    "cash_handling": "Recount and review the cash-up.",
    "demand_shift": "Watch demand over the next days.",
    "weather": "No action: weather-driven.",
}


@dataclass
class Chain:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, str]]

    def add(self, node: dict[str, Any], to: str | None = "anomaly") -> None:
        if any(n["id"] == node["id"] for n in self.nodes):
            return
        self.nodes.append(node)
        if to:
            self.edges.append({"from": node["id"], "to": to})


async def investigate(ctx: SiteContext, anomaly: Anomaly, *, related: list[Anomaly] | None = None) -> Investigation:
    if anomaly.severity == "info":
        raise ValueError("info anomalies are not auto-investigated")
    prior = (await ctx.session.execute(select(Investigation).where(
        Investigation.anomaly_id == anomaly.id).order_by(Investigation.version.desc()).limit(1))).scalar_one_or_none()
    family = FAMILY.get(anomaly.detector, "other")
    day = anomaly.period_end
    baseline_days = same_weekdays(day, ctx.config.get("detection.baseline_weeks"))
    days = await load_days(ctx.session, ctx.site_id, [day, *baseline_days])
    h = HContext(ctx, family, day, baseline_days, days, anomaly_facts=anomaly.facts)
    chain = Chain([], [])
    chain.add(anomaly_node(ctx, anomaly), to=None)

    if family == REVENUE:
        await revenue_drivers(h, anomaly, chain)
    elif family == MARGIN:
        await margin_drivers(h, anomaly, chain)
    if family in (REVENUE, "supply"):
        await load_stock_outs(h)

    for name, (families, test) in LIBRARY.items():
        if family not in families or name == "demand_shift":
            continue
        if (result := await test(h)) is not None:
            h.results.append(result)
    if family == REVENUE and (result := await LIBRARY["demand_shift"][1](h)) is not None:
        h.results.append(result)

    causes = combine(h.results)
    causal = {e for r in h.results if r.verdict == "supports" for e in r.entities}
    entities = {f"{anomaly.subject['type']}:{anomaly.subject['id']}"} | causal | {f"menu_item:{i}" for i in h.focus_items}
    recalls = await similar_cases(ctx, anomaly, causal or entities, causes, day)
    if recalls:
        add_memory_evidence(h, causes, recalls, chain)
    min_conf = Decimal(str(ctx.config.get("investigation.min_cause_confidence")))
    visible = sorted((c for c in causes.values() if c["confidence"] >= min_conf), key=lambda c: -c["confidence"])

    for r in h.results:
        for node in r.nodes:
            if r.verdict == "supports":
                chain.add(node, to=f"cause:{r.cause_code}")
            else:
                chain.add({**node, "status": "ruled_out" if r.verdict == "refutes" else "neutral"}, to="ruled_out")
    ruled_out = [r for r in h.results if r.verdict == "refutes" and r.nodes]
    if ruled_out:
        chain.add({"id": "ruled_out", "kind": "ruled_out", "label": "Ruled out",
                   "facts": {r.test: r.summary for r in ruled_out}}, to="anomaly")
    for c in visible:
        chain.add({"id": f"cause:{c['cause_code']}", "kind": "cause", "label": cause_label(c),
                   "facts": {"confidence": float(c["confidence"]), "chain": c["chain"], "timing": float(c["timing"])}},
                  to="anomaly")
    if family == REVENUE and h.focus_items:
        await margin_side_node(h, chain)

    finding = template_finding(anomaly, chain, visible)
    drafts = draft_recommendations(h, anomaly, visible, ctx)
    template = template_narrative(finding, chain, visible)
    narrative, source, problems = await narrate(ctx, chain, visible, template)
    top = visible[0]["confidence"] if visible else ZERO
    inv = Investigation(
        organisation_id=ctx.organisation_id, site_id=ctx.site_id, anomaly_id=anomaly.id,
        version=(prior.version + 1) if prior else 1, finding=finding[:2000],
        graph={"nodes": chain.nodes, "edges": chain.edges, "entities": sorted(entities),
               "causal_entities": sorted(causal),
               "window": {"start": anomaly.period_start.isoformat(), "end": day.isoformat()},
               "baseline_dates": [d.isoformat() for d in baseline_days if days[d].traded],
               "related_anomalies": [str(a.id) for a in related or []]},
        confidence=top,
        narrative={"text": narrative, "source": source, "ai_generated": source == "ai", "guard_violations": problems,
                   "causes": [{"cause_code": c["cause_code"], "confidence": float(c["confidence"]),
                               "chain": c["chain"], "node_ids": c["node_ids"], "label": cause_label(c)} for c in visible],
                   "similar_cases": [r.as_facts() for r in recalls]},
        draft_recommendations=drafts, status="complete", completed_at=datetime.now(UTC),
    )
    ctx.session.add(inv)
    anomaly.status = "investigating"
    anomaly.investigated_severity = anomaly.severity
    await ctx.session.flush()
    return inv


def anomaly_node(ctx: SiteContext, a: Anomaly) -> dict[str, Any]:
    f = a.facts
    facts: dict[str, Any] = {"detector": a.detector, "severity": a.severity, "date": a.period_end.isoformat(),
                             "weekday": a.period_end.strftime("%A")}
    money = {"revenue_ex_vat_minor", "daypart_revenue_ex_vat_minor", "cash_variance_minor", "item_cost_minor"}
    for k in ("observed", "expected"):
        if k in f and f[k] is not None:
            facts[k] = major(f[k]) if f.get("metric") in money else f[k]
    for k in ("deviation_pct", "rise_pct", "drop_points", "gp_from", "gp_to", "out_at", "daypart"):
        if f.get(k) is not None:
            facts[k] = f[k]
    if f.get("baseline_n"):
        facts["baseline_weeks"] = f["baseline_n"]
    return {"id": "anomaly", "kind": "anomaly", "label": a.subject.get("name") or a.detector, "facts": facts}


# --------------------------------------------------------------------------------------------------
# Driver trees
# --------------------------------------------------------------------------------------------------
async def revenue_drivers(h: HContext, anomaly: Anomaly, chain: Chain) -> None:
    ctx, t = h.ctx, h.today
    base = [h.days[d] for d in h.baseline_days if h.days[d].traded]
    if not base or not t.traded:
        return
    n = Decimal(len(base))
    o0 = sum((Decimal(f.orders) for f in base), ZERO) / n
    r0 = sum((Decimal(f.revenue) for f in base), ZERO) / n
    s0 = r0 / o0
    o1, s1 = Decimal(t.orders), t.spend
    total, d_orders, d_spend = decompose_revenue(o0, s0, o1, s1)
    units0: dict[uuid.UUID, tuple[Decimal, Decimal]] = {}
    for f in base:
        for item, u in f.item_units.items():
            pu, pr = units0.get(item, (ZERO, ZERO))
            units0[item] = (pu + u / n, pr + Decimal(f.item_revenue.get(item, 0)) / n)
    now = {i: (u, Decimal(t.item_revenue.get(i, 0))) for i, u in t.item_units.items()}
    split = split_spend(d_spend, o0, o1, units0, now)
    chain.add({"id": "decomposition", "kind": "driver", "label": "Revenue = orders x average spend", "facts": {
        "orders_pct": r2((o1 - o0) / o0 * 100), "spend_pct": r2((s1 - s0) / s0 * 100),
        "orders_effect": major(d_orders), "spend_effect": major(d_spend), "total_change": major(total),
        "mix_effect_pct": r2(split.mix_effect / r0 * 100), "price_effect_pct": r2(split.price_effect / r0 * 100)}})

    # Group the item contributions by shared ingredient; the group holding most of the drop is the focus.
    from app.domain.detectors.stock_out import recipe_uses

    uses = await recipe_uses(ctx, h.day)
    by_ing: dict[uuid.UUID, list] = {}
    for e in split.items:
        for ing in uses.get(e.menu_item_id, {}):
            by_ing.setdefault(ing, []).append(e)
    negative = sum((-e.contribution for e in split.items if e.contribution < 0), ZERO)
    best = None
    for ing, effects in by_ing.items():
        if len(effects) < 2:
            continue
        drop = sum((-e.contribution for e in effects if e.contribution < 0), ZERO)
        if best is None or drop > best[1]:
            best = (ing, drop, effects)
    names = {i: n for i, n in (await ctx.session.execute(select(MenuItem.id, MenuItem.name).where(
        MenuItem.organisation_id == ctx.organisation_id))).all()}
    if best and negative > 0 and d_spend < 0:
        ing, drop, effects = best
        from app.domain.inventory.models import Ingredient

        ing_name = (await ctx.session.execute(select(Ingredient.name).where(Ingredient.id == ing))).scalar_one()
        u0 = sum((e.units0 for e in effects), ZERO)
        u1 = sum((e.units1 for e in effects), ZERO)
        lead = min(effects, key=lambda e: e.contribution)
        share = clip(drop / -d_spend)
        h.focus_items = {e.menu_item_id: names.get(e.menu_item_id, "?") for e in effects}
        h.focus_ingredients = {ing}
        h.focus_share = share
        chain.add({"id": "items", "kind": "driver", "label": f"Dishes with {ing_name.lower()}", "facts": {
            "ingredient": ing_name, "dishes": len(effects), "units_pct": r2((u1 - u0) / u0 * 100) if u0 else 0,
            "lead_item": names.get(lead.menu_item_id), "lead_units_pct": r2(
                (lead.units1 - lead.units0) / lead.units0 * 100) if lead.units0 else 0,
            "share_of_spend_change_pct": r2(share * 100)}}, to="decomposition")

    # Segments: day x daypart (single-day anomaly: the dayparts of that day).
    segments = {dp: Decimal(t.daypart_revenue.get(dp, 0)) - sum(
        (Decimal(f.daypart_revenue.get(dp, 0)) for f in base), ZERO) / n
        for dp in {*t.daypart_revenue, *(dp for f in base for dp in f.daypart_revenue)}}
    seg, seg_share = concentration(segments)
    if seg:
        windows = {d.name: d for d in ctx.config.get("site.dayparts")}
        w = windows.get(seg)
        if w is not None:
            h.effect_start = ctx.local(h.day, w.start)
            h.effect_end = ctx.local(h.day, w.end)
        facts: dict[str, Any] = {"segment": f"{h.day.strftime('%A')} {seg}", "share_pct": r2(seg_share * 100),
                                 "concentrated": seg_share >= Decimal("0.6"), "segment_change": major(segments[seg])}
        if h.focus_items:
            last = (await ctx.session.execute(select(SalesOrderLine.sold_at).where(
                SalesOrderLine.site_id == ctx.site_id, SalesOrderLine.business_date == h.day,
                SalesOrderLine.menu_item_id.in_(list(h.focus_items)), SalesOrderLine.quantity > 0).order_by(
                SalesOrderLine.sold_at.desc()).limit(1))).scalar_one_or_none()
            if last is not None:
                facts["last_focus_sale"] = last.astimezone(ctx.tz).strftime("%H:%M")
        chain.add({"id": "concentration", "kind": "segment", "label": "Where the change happened", "facts": facts},
                  to="decomposition")


async def margin_drivers(h: HContext, anomaly: Anomaly, chain: Chain) -> None:
    ctx = h.ctx
    if anomaly.subject.get("type") != "menu_item":
        if anomaly.detector == "price_increase":
            h.focus_ingredients = {uuid.UUID(anomaly.subject["id"])}
        return
    item = uuid.UUID(anomaly.subject["id"])
    start = anomaly.period_start if anomaly.period_start < anomaly.period_end else anomaly.period_end - timedelta(days=28)
    attr = await item_attribution(ctx.session, organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                                  menu_item_id=item, date_from=start, date_to=anomaly.period_end)
    h.focus_items = {item: anomaly.subject.get("name", "?")}
    if attr is None:
        return
    h.item_cost_drivers = attr.drivers
    h.anomaly_facts = {**h.anomaly_facts, "item_cost_from_minor": attr.cost_from_minor}
    h.focus_ingredients = {d.ingredient_id for d in attr.drivers[:1]}
    chain.add({"id": "item_cost", "kind": "driver", "label": "Item cost by ingredient", "facts": {
        "cost_from": major(attr.cost_from_minor), "cost_to": major(attr.cost_to_minor),
        "gp_from": r2(attr.gp_from_pct), "gp_to": r2(attr.gp_to_pct),
        "drivers": {d.ingredient_name: r2(d.pct_of_change) for d in attr.drivers[:3]}}})


async def margin_side_node(h: HContext, chain: Chain) -> None:
    """The lead dish's cost and GP over 28 days (Appendix B 'Margin')."""
    ctx = h.ctx
    start = h.day - timedelta(days=28)
    gp = {(i, d): Decimal(g) for i, d, g in (await ctx.session.execute(select(
        ItemCostSnapshot.menu_item_id, ItemCostSnapshot.business_date, ItemCostSnapshot.gp_pct).where(
        ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.menu_item_id.in_(list(h.focus_items)),
        ItemCostSnapshot.business_date.in_([start, h.day])))).all()}
    drops = {i: gp[(i, start)] - gp[(i, h.day)] for i in h.focus_items if (i, start) in gp and (i, h.day) in gp}
    if not drops:
        return
    lead = max(drops, key=lambda i: drops[i])  # the dish whose margin moved most
    attr = await item_attribution(ctx.session, organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                                  menu_item_id=lead, date_from=start, date_to=h.day)
    if attr is None or attr.cost_to_minor == attr.cost_from_minor:
        return
    top = attr.drivers[0] if attr.drivers else None
    chain.add({"id": "margin", "kind": "margin", "label": f"{h.focus_items.get(lead)} margin", "facts": {
        "item": h.focus_items.get(lead), "cost_from": major(attr.cost_from_minor), "cost_to": major(attr.cost_to_minor),
        "gp_from": r2(attr.gp_from_pct), "gp_to": r2(attr.gp_to_pct),
        "top_driver": top.ingredient_name if top else None, "top_driver_pct": r2(top.pct_of_change) if top else None,
        "date_from": start.isoformat()}}, to=None)


# --------------------------------------------------------------------------------------------------
# Confidence and memory
# --------------------------------------------------------------------------------------------------
def combine(results: list[Result]) -> dict[str, dict[str, Any]]:
    causes: dict[str, dict[str, Any]] = {}
    for r in results:
        if r.verdict != "supports":
            continue
        c = causes.setdefault(r.cause_code, {"cause_code": r.cause_code, "supporting": [], "timing": Decimal(1),
                                             "refuting": ZERO, "node_ids": [], "chain": [r.cause_code]})
        c["supporting"] += r.supporting
        c["timing"] = min(c["timing"], r.timing)
        c["refuting"] = max(c["refuting"], r.refuting)
        c["node_ids"] += [n["id"] for n in r.nodes]
        if len(r.chain) > len(c["chain"]):
            c["chain"] = r.chain
    # A cause that is the mechanism of a deeper cause is folded into that cause's chain.
    for c in list(causes.values()):
        for step in c["chain"][1:]:
            if step in causes and step != c["cause_code"]:
                causes[step]["mechanism_of"] = c["cause_code"]
    for c in causes.values():
        c["confidence"] = cause_confidence(c["supporting"], timing=c["timing"], max_refuting=c["refuting"])
    return causes


async def similar_cases(ctx: SiteContext, anomaly: Anomaly, entities: set[str], causes: dict[str, dict[str, Any]],
                        day: date) -> list[Recall]:
    top = max(causes.values(), key=lambda c: c["confidence"])["cause_code"] if causes else None
    query = " ".join([anomaly.detector.replace("_", " "), *(CAUSE_LABEL.get(c, c) for c in causes),
                      *(str(v) for v in anomaly.subject.values() if isinstance(v, str))])
    from app.domain.actions.models import OperationsCase

    case_id = (await ctx.session.execute(select(OperationsCase.id).where(
        OperationsCase.anomaly_id == anomaly.id))).scalar_one_or_none()
    return await retrieve(ctx, subjects=entities - {f"site:{ctx.site_id}"}, cause_code=top, query_text=query,
                          on=day - timedelta(days=1), exclude_case_id=case_id)


def add_memory_evidence(h: HContext, causes: dict[str, dict[str, Any]], recalls: list[Recall], chain: Chain) -> None:
    for i, r in enumerate(recalls):
        node_id = f"memory:{i + 1}"
        chain.add({"id": node_id, "kind": "memory", "label": f"Similar case {r.occurred_on.strftime('%d %b')}",
                   "facts": {**r.as_facts(), "date_label": r.occurred_on.strftime("%d %b")}}, to=None)
        c = causes.get(r.cause_code or "")
        if c is not None:
            c["supporting"].append((W["similar_case"], clip(r.score)))
            c["node_ids"].append(node_id)
            c["confidence"] = cause_confidence(c["supporting"], timing=c["timing"], max_refuting=c["refuting"])


def cause_label(c: dict[str, Any]) -> str:
    return " → ".join(str(CAUSE_LABEL.get(s) or s.replace("_", " ")) for s in c["chain"])


# --------------------------------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------------------------------
def draft_recommendations(h: HContext, anomaly: Anomaly, causes: list[dict[str, Any]], ctx: SiteContext) -> list[dict]:
    """FR-RCA-06: next actions as recommendation drafts; the Action Centre generators price them."""
    drafts: list[dict[str, Any]] = []
    low = Decimal(str(ctx.config.get("investigation.low_confidence")))
    codes = {c["cause_code"] for c in causes}
    ingredient = next(iter(h.focus_ingredients), None)
    if ingredient and codes & {"supplier_short_delivery", "supplier_price_increase"}:
        drafts.append({"type": "supplier_switch", "subject": {"type": "ingredient", "id": str(ingredient)},
                       "reason": "Supplier short delivery or price increase on this ingredient"})
    if ingredient and codes & {"stock_out", "supplier_short_delivery"} and h.stock_outs:
        drafts.append({"type": "par_level_change", "subject": {"type": "ingredient", "id": str(ingredient)},
                       "reason": "Stock-out during service"})
    for item in h.focus_items:
        drafts.append({"type": "price_review", "subject": {"type": "menu_item", "id": str(item)},
                       "reason": "Dish GP below target after cost increase", "only_if_below_target": True})
    if anomaly.detector in ("discount_spike", "void_spike", "cash_variance"):
        drafts.append({"type": "investigate_task", "subject": anomaly.subject, "reason": f"Review {anomaly.detector}"})
    if anomaly.detector == "labour_over_target":
        drafts.append({"type": "staffing_change", "subject": anomaly.subject, "reason": "Labour over target"})
    if anomaly.detector == "cogs_drift":
        drafts.append({"type": "waste_reduction", "subject": anomaly.subject, "reason": "COGS above baseline"})
    if not causes or causes[0]["confidence"] < low:
        drafts.append({"type": "investigate_task", "subject": anomaly.subject,
                       "reason": "Low-confidence cause: needs a manager's review"})
    return drafts


def _fmt(v: Any, decimals: int = 2) -> str:
    if isinstance(v, (int, float, Decimal)):
        return f"{Decimal(str(v)):,.{decimals}f}"
    return str(v)


def describe(node: dict[str, Any]) -> str:
    f = node["facts"]
    k = node["kind"]
    if k == "anomaly":
        if "observed" in f and "expected" in f and "deviation_pct" in f:
            return (f"{f['weekday']} {node['label'] if f['detector'] != 'revenue_day' else 'revenue'} "
                    f"{_fmt(f['observed'], 0)} vs {_fmt(f['expected'], 0)} baseline ({_fmt(f['deviation_pct'], 1)}%, "
                    f"{f['severity']}).")
        what = f["detector"].replace("_", " ")
        if "observed" in f and "expected" in f:
            return (f"{node['label']}: {what} {_fmt(f['observed'], 1)} vs {_fmt(f['expected'], 1)} expected "
                    f"({f['severity']}).")
        return f"{node['label']}: {what} ({f['severity']})."
    if node["id"] == "decomposition":
        return (f"Orders {_fmt(f['orders_pct'], 1)}%, average spend {_fmt(f['spend_pct'], 1)}%; mix effect "
                f"{_fmt(f['mix_effect_pct'], 1)}%, price effect {_fmt(f['price_effect_pct'], 1)}%.")
    if node["id"] == "items":
        return (f"{node['label'].capitalize()} ({f['dishes']} items) units {_fmt(f['units_pct'], 0)}%, led by "
                f"{f['lead_item']} {_fmt(f['lead_units_pct'], 0)}%; {_fmt(f['share_of_spend_change_pct'], 0)}% of the "
                f"spend change.")
    if node["id"] == "concentration":
        tail = f"; none sold after {f['last_focus_sale']}" if f.get("last_focus_sale") else ""
        return f"{_fmt(f['share_pct'], 0)}% of the drop in {f['segment']}{tail}."
    if node["id"] == "stock":
        return (f"{f['ingredient']} on hand {_fmt(f['on_hand'], 1)} {f['unit']} at {f['out_at']}; need for the rest of the "
                f"day {_fmt(f['need_after'], 1)} {f['unit']}.")
    if node["id"] == "purchasing":
        price = ""
        if f.get("price") is not None and f.get("median_price_90d") is not None:
            price = (f"; price {_fmt(f['price'])}/{f['unit']} vs 90-day median {_fmt(f['median_price_90d'])}/{f['unit']} "
                     f"({_fmt(f['price_change_pct'], 0)}%)")
        received = f["invoiced"] if f.get("invoiced") is not None else f["received"]
        return (f"{f.get('invoice_number') or f['po_number']} from {f['supplier']}: {_fmt(received, 0)} {f['unit']} vs "
                f"{_fmt(f['ordered'], 0)} {f['unit']} on the PO ({_fmt(f['short_pct'], 0)}% short){price}.")
    if node["id"] == "link":
        return (f"{_fmt(f['missing'], 1)} {f['unit']} missing against {_fmt(f['need_after'], 1)} {f['unit']} needed after "
                f"{f['out_at']}.")
    if node["id"] == "margin":
        return (f"{f['item']} cost {_fmt(f['cost_from'])} → {_fmt(f['cost_to'])} ({f['top_driver']} explains "
                f"{_fmt(f['top_driver_pct'], 0)}% of the increase); GP {_fmt(f['gp_from'], 1)}% → {_fmt(f['gp_to'], 1)}%.")
    if node["id"] == "cost":
        return (f"{f['ingredient']} ({f['supplier']}) {_fmt(f['cost_from'])} → {_fmt(f['cost_to'])} per portion; "
                f"{_fmt(f['share_pct'], 0)}% of the item cost change.")
    if node["id"] == "item_cost":
        return (f"Cost {_fmt(f['cost_from'])} → {_fmt(f['cost_to'])}; GP {_fmt(f['gp_from'], 1)}% → "
                f"{_fmt(f['gp_to'], 1)}%.")
    if node["id"] == "ruled_out":
        return "Ruled out: " + " ".join(f.values())
    if k == "memory":
        return f"Similar case {f['date_label']}: {f['summary']}"
    if k == "cause":
        return f"{node['label']}; confidence {_fmt(f['confidence'])}."
    return f"{node['label']}: " + ", ".join(f"{a} {_fmt(b) if isinstance(b, (int, float)) else b}"
                                            for a, b in f.items() if not isinstance(b, (dict, list)))


def template_finding(anomaly: Anomaly, chain: Chain, causes: list[dict[str, Any]]) -> str:
    head = describe(chain.nodes[0])
    if not causes:
        return f"{head} No cause reached the confidence threshold; a review task was opened."
    top = causes[0]
    return f"{head} Most likely cause: {cause_label(top)} (confidence {_fmt(top['confidence'])})."


def template_narrative(finding: str, chain: Chain, causes: list[dict[str, Any]]) -> InvestigationNarrative:
    evidence = [{"node_id": n["id"], "text": describe(n)} for n in chain.nodes
                if n["kind"] != "cause" and "status" not in n]
    return InvestigationNarrative.model_validate({
        "finding": finding,
        "evidence": evidence,
        "causes": [{"cause_code": c["cause_code"], "confidence_node_id": f"cause:{c['cause_code']}",
                    "text": f"{cause_label(c)}; confidence {_fmt(c['confidence'])}."} for c in causes[:3]],
        "next_action": NEXT_ACTION.get(causes[0]["cause_code"], "Review the evidence.") if causes else
        "Review the evidence and add a note.",
    })


async def narrate(ctx: SiteContext, chain: Chain, causes: list[dict[str, Any]], template: InvestigationNarrative,
                  ) -> tuple[dict[str, Any], str, list[str]]:
    """FR-RCA-07: Gemini narrates the evidence graph (A.3) citing node ids; the Number Guard checks every
    number against the cited node's facts; the deterministic template is the fallback."""
    facts = {"nodes": chain.nodes, "causes": [{"cause_code": c["cause_code"], "confidence": float(c["confidence"]),
                                               "node_id": f"cause:{c['cause_code']}"} for c in causes],
             "template": template.model_dump(mode="json")}
    instructions = (
        "Explain this restaurant investigation to the general manager in plain English. Use only the nodes "
        "given: every evidence item and cause must cite an existing node id, and every number you write must "
        "appear in that node's facts (rounded as written). Do not add history, causes or numbers that are not "
        "in the facts. Keep each text under 40 words."
    )
    try:
        ai = await ctx.adapter(IntegrationKind.ai)
        result, _info = await ai.narrate(facts, InvestigationNarrative, instructions)
        payload = result.model_dump(mode="json")
        problems = check_narrative(payload, chain.nodes)
        if not problems:
            return payload, "ai" if getattr(ai, "provider", "") != "fake" else "template", []
        log.info("narrative rejected by the Number Guard", extra={"violations": problems[:5]})
        return template.model_dump(mode="json"), "template", problems
    except Exception:  # any AI failure falls back to the template
        log.warning("narrative unavailable; template used", exc_info=True)
        return template.model_dump(mode="json"), "template", []


__all__ = ["check_narrative", "investigate", "template_narrative"]
