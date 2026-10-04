"""Pure inventory rules (no I/O): money of a quantity at a unit cost, weighted average cost."""

from decimal import ROUND_HALF_UP, Decimal


def money_minor(qty: Decimal, unit_cost: Decimal) -> int:
    """Value in minor units of `qty` base units at `unit_cost` minor units per base unit (half-up)."""
    return int((qty * unit_cost).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def new_wac(on_hand: Decimal, wac: Decimal, qty_in: Decimal, price_per_base: Decimal) -> Decimal:
    """Weighted average cost after a receipt (FR-STK-09). Zero or negative stock resets to the receipt price."""
    if on_hand <= 0:
        return price_per_base
    return ((on_hand * wac + qty_in * price_per_base) / (on_hand + qty_in)).quantize(Decimal("0.000001"))
