"""Cause confidence formula (SRS §4.3)."""

from decimal import Decimal

ZERO = Decimal(0)


def cause_confidence(
    supporting: list[tuple[Decimal, Decimal]],
    *,
    timing: Decimal = Decimal("1"),
    max_refuting: Decimal = ZERO,
) -> Decimal:
    product = Decimal("1")
    for weight, strength in supporting:
        product *= Decimal("1") - weight * strength
    score = (Decimal("1") - product) * timing * (Decimal("1") - max_refuting)
    return score.quantize(Decimal("0.0001"))
