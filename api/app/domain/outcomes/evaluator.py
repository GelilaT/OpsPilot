"""Outcome measurement (FR-ACT-06/07) and the memory it writes (FR-MEM-01).

    effect = mean(metric after action) - counterfactual
    counterfactual = pre-period trend projected forward (robust Theil-Sen slope from the last value)
    improved  if the effect has the expected sign and |effect| >= 0.5 x |expected|
    worsened  if the effect has the opposite sign and |effect| > one standard deviation of the pre-period
    otherwise no_change

Success metrics: cost_per_base_unit (cost per base unit paid on the day's receipts), stock_out_count (stock-outs per day of the
ingredient), item_gp_pct, labour_pct, usage_variance (COGS % as the proxy until counts exist) and
task_closed. Measured recommendations move to `outcome_measured`; when a case has nothing left to measure
or approve it closes, and its memory entry records what happened, what was done and whether it worked.
"""

import logging
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median, pstdev
from typing import Any

from sqlalchemy import func, select

from app.core.tenancy.context import SiteContext
from app.domain.actions.models import OperationsCase, OpsTask, Recommendation, RecommendationOutcome
from app.domain.actions.service import add_event, refresh_case, transition
from app.domain.detectors.data import load_days
from app.domain.detectors.stock_out import find_stock_outs
from app.domain.intelligence.models import Anomaly, Investigation, ItemCostSnapshot
from app.domain.memory.service import upsert_entry

log = logging.getLogger("opspilot.outcomes")
ZERO = Decimal(0)
PRE_DAYS = 14


def theil_sen(values: list[Decimal]) -> Decimal:
    slopes = [(values[j] - values[i]) / (j - i) for i in range(len(values)) for j in range(i + 1, len(values))]
    return Decimal(str(median(slopes))) if slopes else ZERO


def counterfactual(pre: list[Decimal], horizon: int) -> Decimal:
    """The pre-period trend projected over the post window (mean of the projected days)."""
    if not pre:
        return ZERO
    slope = theil_sen(pre)
    last = pre[-1]
    return last + slope * Decimal(horizon + 1) / 2


def verdict(effect: Decimal, expected: Decimal, sigma: Decimal) -> str:
    if expected != 0 and (effect * expected) > 0 and abs(effect) >= abs(expected) / 2:
        return "improved"
    if expected != 0 and (effect * expected) < 0 and abs(effect) > sigma:
        return "worsened"
    return "no_change"


async def _purchase_cost_series(ctx: SiteContext, ingredient_id: uuid.UUID, days: list[date]) -> list[Decimal]:
    """Cost per base unit paid on each day's receipts (days without a delivery carry no observation)."""
    from app.domain.inventory.models import StockMovement

    rows = dict((await ctx.session.execute(select(
        StockMovement.business_date, func.sum(StockMovement.cost_minor) / func.sum(StockMovement.qty_base)).where(
        StockMovement.site_id == ctx.site_id, StockMovement.ingredient_id == ingredient_id,
        StockMovement.type == "receipt", StockMovement.business_date.in_(days)).group_by(
        StockMovement.business_date))).all())
    return [Decimal(rows[d]) for d in days if d in rows]


async def metric_series(ctx: SiteContext, rec: Recommendation, days: list[date]) -> list[Decimal]:
    m = rec.success_metric
    if m == "cost_per_base_unit":
        return await _purchase_cost_series(ctx, uuid.UUID(rec.subject["id"]), days)
    if m == "stock_out_count":
        ing = uuid.UUID(rec.subject["id"])
        out = []
        for d in days:
            baseline = [d - timedelta(weeks=i) for i in range(1, 5)]
            events = await find_stock_outs(ctx, d, baseline, ingredient_ids={ing})
            out.append(Decimal(len(events)))
        return out
    if m == "item_gp_pct":
        rows = dict((await ctx.session.execute(select(ItemCostSnapshot.business_date, ItemCostSnapshot.gp_pct).where(
            ItemCostSnapshot.site_id == ctx.site_id, ItemCostSnapshot.menu_item_id == uuid.UUID(rec.subject["id"]),
            ItemCostSnapshot.business_date.in_(days)))).all())
        return [Decimal(rows[d]) for d in days if d in rows]
    if m in ("labour_pct", "usage_variance"):
        facts = await load_days(ctx.session, ctx.site_id, days)
        num = (lambda f: f.labour_cost) if m == "labour_pct" else (lambda f: f.cogs)
        return [Decimal(num(facts[d])) / facts[d].revenue * 100 for d in days if facts[d].revenue]
    return []


def expected_effect(rec: Recommendation, pre_value: Decimal) -> Decimal:
    """Expected change of the success metric, in the metric's units (sign = desired direction)."""
    i = rec.impact_inputs
    if rec.success_metric == "cost_per_base_unit":
        return -Decimal(str(i.get("price_delta_per_base", 0)))
    if rec.success_metric == "stock_out_count":
        return -Decimal(str(i.get("events_per_week", 0.25))) / 7
    if rec.success_metric == "item_gp_pct":
        return Decimal(str(i.get("suggested_gp_pct", 0))) - Decimal(str(i.get("current_gp_pct", 0)))
    if rec.success_metric in ("labour_pct", "usage_variance"):
        return -abs(pre_value) * Decimal("0.05")
    return Decimal(1)


def _r(v: Decimal, places: str = "0.0001") -> Decimal:
    return v.quantize(Decimal(places), rounding=ROUND_HALF_UP)


async def measure(ctx: SiteContext, rec: Recommendation, today: date) -> RecommendationOutcome:
    # The business date of execution (the follow-up date is set from it; on the simulator clock the wall-clock
    # execution time is not the business date).
    executed = (rec.follow_up_at or today) - timedelta(days=ctx.config.get("actions.follow_up_days"))
    post_start = executed + timedelta(days=1)
    post_end = min(rec.follow_up_at or today, today)
    pre_start = executed - timedelta(days=PRE_DAYS - 1)
    pre_days = [pre_start + timedelta(days=i) for i in range(PRE_DAYS)]
    post_days = [post_start + timedelta(days=i) for i in range((post_end - post_start).days + 1)]
    facts: dict[str, Any] = {}
    if rec.success_metric == "task_closed":
        closed = (await ctx.session.execute(select(func.count()).select_from(OpsTask).where(
            OpsTask.recommendation_id == rec.id, OpsTask.status == "closed"))).scalar() or 0
        pre, post, cf, actual = [ZERO], [Decimal(1 if closed else 0)], ZERO, Decimal(1 if closed else 0)
    else:
        pre = await metric_series(ctx, rec, pre_days)
        post = await metric_series(ctx, rec, post_days)
        cf = counterfactual(pre, len(post_days))
        actual = sum(post, ZERO) / len(post) if post else cf
    effect = actual - cf
    expected = expected_effect(rec, pre[-1] if pre else ZERO)
    sigma = Decimal(str(pstdev([float(v) for v in pre]))) if len(pre) > 1 else ZERO
    v = verdict(effect, expected, sigma)
    facts.update({"pre_values": [float(_r(x)) for x in pre], "post_values": [float(_r(x)) for x in post],
                  "slope": float(_r(theil_sen(pre))) if pre else 0.0})
    outcome = RecommendationOutcome(
        organisation_id=ctx.organisation_id, site_id=ctx.site_id, recommendation_id=rec.id, case_id=rec.case_id,
        metric=rec.success_metric or "-", pre_start=pre_start, post_start=post_start, post_end=post_end,
        counterfactual=_r(cf, "0.000001"), actual=_r(actual, "0.000001"), effect=_r(effect, "0.000001"),
        effect_pct=_r(effect / cf * 100) if cf else None, expected_effect=_r(expected, "0.000001"),
        sigma=_r(sigma, "0.000001"), verdict=v, facts=facts)
    ctx.session.add(outcome)
    await ctx.session.flush()
    return outcome


def outcome_text(rec: Recommendation, o: RecommendationOutcome) -> str:
    metric = (o.metric or "").replace("_", " ")
    pct = f" ({o.effect_pct:+.1f}% vs counterfactual)" if o.effect_pct is not None else ""
    return f"{metric}: {o.verdict}{pct}"


async def evaluate_due(ctx: SiteContext, today: date) -> dict[str, Any]:
    """06:00: measure every recommendation in follow_up whose follow-up date has passed."""
    due = (await ctx.session.execute(select(Recommendation).where(
        Recommendation.site_id == ctx.site_id, Recommendation.status == "follow_up",
        Recommendation.follow_up_at <= today).with_for_update())).scalars().all()
    measured: list[dict[str, Any]] = []
    cases: set[uuid.UUID] = set()
    for rec in due:
        outcome = await measure(ctx, rec, today)
        add_event(ctx, rec.case_id, "outcome_measured", f"{rec.parameters.get('title', rec.type)}: "
                  f"{outcome_text(rec, outcome)}.", {"type": "recommendation_outcome", "id": str(outcome.id)},
                  actor="agent")
        await transition(ctx, rec, "outcome_measured", reason=outcome_text(rec, outcome))
        measured.append({"recommendation_id": str(rec.id), "verdict": outcome.verdict,
                         "effect_pct": float(outcome.effect_pct) if outcome.effect_pct is not None else None})
        cases.add(rec.case_id)
    for case_id in cases:
        await write_case_memory(ctx, case_id, kind="outcome")
    return {"measured": measured, "cases": [str(c) for c in cases]}


async def write_case_memory(ctx: SiteContext, case_id: uuid.UUID, *, kind: str) -> None:
    """FR-MEM-01: what happened, why, what was done and whether it worked - templated from records."""
    case = (await ctx.session.execute(select(OperationsCase).where(OperationsCase.id == case_id))).scalar_one()
    anomaly = (await ctx.session.execute(select(Anomaly).where(Anomaly.id == case.anomaly_id))).scalar_one()
    inv = (await ctx.session.execute(select(Investigation).where(
        Investigation.id == case.investigation_id))).scalar_one_or_none() if case.investigation_id else None
    recs = (await ctx.session.execute(select(Recommendation).where(Recommendation.case_id == case_id))).scalars().all()
    outcomes = {o.recommendation_id: o for o in (await ctx.session.execute(select(RecommendationOutcome).where(
        RecommendationOutcome.case_id == case_id))).scalars()}
    causes = (inv.narrative.get("causes") if inv else None) or []
    top = causes[0] if causes else None
    subjects = [anomaly.subject] + [r.subject for r in recs]
    entities = set(inv.graph.get("entities", [])) if inv else set()
    for key in entities:
        kind_, _, ident = key.partition(":")
        if kind_ in ("ingredient", "supplier", "menu_item") and not any(
                f"{s.get('type')}:{s.get('id')}" == key for s in subjects):
            subjects.append({"type": kind_, "id": ident})
    done = [r for r in recs if r.status in ("completed", "follow_up", "outcome_measured")]
    actions = [{"recommendation_id": str(r.id), "type": r.type, "title": r.parameters.get("title", r.type),
                "status": r.status, "verdict": outcomes[r.id].verdict if r.id in outcomes else None} for r in recs]
    verdicts = [o.verdict for o in outcomes.values()]
    overall = "improved" if "improved" in verdicts else ("worsened" if "worsened" in verdicts else
                                                         ("no_change" if verdicts else None))
    what = inv.finding if inv else anomaly.detector
    did = "; ".join(a["title"] + (f" ({a['verdict']})" if a["verdict"] else "") for a in actions if a["status"] in (
        "completed", "follow_up", "outcome_measured")) or "no action taken"
    summary = (f"{anomaly.period_end.strftime('%d %b %Y')}: {top['label'] if top else anomaly.detector}. {what} "
               f"Actions: {did}.")
    await upsert_entry(ctx, case_id=case_id, kind=kind, investigation_id=inv.id if inv else None, subjects=subjects,
                       cause_code=top["cause_code"] if top else None, summary=summary[:4000], actions=actions,
                       outcome={"verdict": overall, "details": [{"type": r.type, "verdict": outcomes[r.id].verdict,
                                                                 "effect_pct": float(outcomes[r.id].effect_pct or 0)}
                                                                for r in done if r.id in outcomes]} if verdicts else None,
                       occurred_on=anomaly.period_end, resolved_on=await ctx.today() if overall else None)
    add_event(ctx, case_id, "memory_written", f"Case written to memory ({kind}).", {"type": "case", "id": str(case_id)},
              actor="agent")
    await refresh_case(ctx, case_id)
