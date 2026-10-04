"""Repricing suggestions (FR-MNU-06): the price that restores the target GP %, rounded up to the site's
price endings, with the weekly GP impact at current volume and at -5% volume. Prices are never changed
automatically; the result feeds a price_review recommendation or the what-if screen."""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from app.domain.menu.margin_engine import gp_pct

VOLUME_DROP = Decimal("0.05")


@dataclass(frozen=True)
class Repricing:
    current_gross_minor: int
    suggested_gross_minor: int
    current_gp_pct: Decimal
    suggested_gp_pct: Decimal
    target_gp_pct: Decimal
    weekly_units: Decimal
    weekly_gp_impact_minor: int  # at current volume
    weekly_gp_impact_lower_volume_minor: int  # at -5% volume


def round_to_endings(gross_minor: int, endings: list[int]) -> int:
    """Smallest price >= gross_minor whose pence part is one of `endings` (e.g. 95, 50, 0)."""
    candidates = []
    pounds = gross_minor // 100
    for p in (pounds, pounds + 1):
        candidates.extend(p * 100 + e for e in endings if p * 100 + e >= gross_minor)
    return min(candidates) if candidates else gross_minor


def ex_vat_exact(gross_minor: int, vat_rate: Decimal) -> Decimal:
    return Decimal(gross_minor) / (1 + vat_rate)


def weekly_gp_impact(cost_minor: int, old_gross: int, new_gross: int, vat_rate: Decimal, weekly_units: Decimal,
                     volume_factor: Decimal = Decimal(1)) -> int:
    old_cm = ex_vat_exact(old_gross, vat_rate) - cost_minor
    new_cm = ex_vat_exact(new_gross, vat_rate) - cost_minor
    delta = weekly_units * volume_factor * new_cm - weekly_units * old_cm
    return int(delta.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def suggest(*, cost_minor: int, current_gross_minor: int, vat_rate: Decimal, target_gp: Decimal,
            endings: list[int], weekly_units: Decimal, gross_override: int | None = None) -> Repricing:
    """`target_gp` as a fraction (0.65). `gross_override` evaluates a manager's own price (what-if)."""
    if gross_override is not None:
        new_gross = gross_override
    else:
        needed_ex = Decimal(cost_minor) / (1 - target_gp)
        needed_gross = int((needed_ex * (1 + vat_rate)).to_integral_value(rounding=ROUND_CEILING))
        new_gross = max(round_to_endings(needed_gross, endings), current_gross_minor)
    current_ex = int(ex_vat_exact(current_gross_minor, vat_rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    new_ex = int(ex_vat_exact(new_gross, vat_rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return Repricing(
        current_gross_minor=current_gross_minor,
        suggested_gross_minor=new_gross,
        current_gp_pct=gp_pct(current_ex, cost_minor),
        suggested_gp_pct=gp_pct(new_ex, cost_minor),
        target_gp_pct=(target_gp * 100).quantize(Decimal("0.1")),
        weekly_units=weekly_units,
        weekly_gp_impact_minor=weekly_gp_impact(cost_minor, current_gross_minor, new_gross, vat_rate, weekly_units),
        weekly_gp_impact_lower_volume_minor=weekly_gp_impact(cost_minor, current_gross_minor, new_gross, vat_rate,
                                                             weekly_units, 1 - VOLUME_DROP),
    )
