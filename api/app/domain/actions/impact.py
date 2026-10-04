"""Expected weekly impact per recommendation type (Recommendation Types table, FR-ACT-02/04).

Every recommendation stores its formula, its inputs and the parameters an approver may adjust; adjusting
re-runs the same formula (`recompute`). Amounts are minor units per week.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.domain.menu.repricing import weekly_gp_impact

ZERO = Decimal(0)

FORMULAS = {
    "supplier_switch": "weekly usage x price difference",
    "par_level_change": "lost GP avoided - holding cost",
    "price_review": "units x price change (current volume; -5% volume shown)",
    "purchase_order": "lost GP avoided",
    "waste_reduction": "variance cost",
    "staffing_change": "hours x rate",
    "investigate_task": "n/a",
}
HOLDING_RATE_WEEKLY = Decimal("0.005")  # capital and spoilage cost of extra stock, per week


def _m(v: Decimal) -> int:
    return int(v.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def supplier_switch(weekly_qty_base: Decimal, price_delta_per_base: Decimal) -> int:
    return _m(weekly_qty_base * price_delta_per_base)


def par_level_change(lost_gp_per_event: int, events_per_week: Decimal, par_from: Decimal, par_to: Decimal,
                     wac_per_base: Decimal) -> int:
    holding = (par_to - par_from) * wac_per_base * HOLDING_RATE_WEEKLY
    return _m(Decimal(lost_gp_per_event) * events_per_week - holding)


def recompute(rec_type: str, parameters: dict[str, Any], inputs: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Re-run a recommendation's formula after an approver adjusted its parameters."""
    d = {k: Decimal(str(v)) for k, v in inputs.items() if isinstance(v, (int, float, str)) and _is_num(v)}
    if rec_type == "supplier_switch":
        impact = supplier_switch(d["weekly_qty_base"], d["price_delta_per_base"])
    elif rec_type == "par_level_change":
        par_to = Decimal(str(parameters["par_level_base"]))
        impact = par_level_change(int(d["lost_gp_per_event"]), d["events_per_week"], d["par_from_base"], par_to,
                                  d["wac_per_base"])
        inputs = {**inputs, "par_to_base": float(par_to)}
    elif rec_type == "price_review":
        gross = int(parameters["suggested_gross_minor"])
        impact = weekly_gp_impact(int(d["cost_minor"]), int(d["current_gross_minor"]), gross, d["vat_rate"],
                                  d["weekly_units"])
        lower = weekly_gp_impact(int(d["cost_minor"]), int(d["current_gross_minor"]), gross, d["vat_rate"],
                                 d["weekly_units"], Decimal("0.95"))
        inputs = {**inputs, "impact_lower_volume_minor": lower}
    elif rec_type == "purchase_order":
        impact = int(d.get("lost_gp_avoided_minor", ZERO))
    else:
        impact = int(d.get("impact_minor", ZERO))
    return impact, inputs


def _is_num(v: Any) -> bool:
    try:
        Decimal(str(v))
        return not isinstance(v, bool)
    except Exception:
        return False
