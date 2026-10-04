"""Units of measure. Every ingredient has a base unit: g, ml or each (SRS glossary "UoM").

Quantities are Decimals with explicit units. Pack expressions such as "2 x 5kg" are normalised to
the base unit (FR-INV-07). Ingredient-specific conversions (e.g. 1 case = 6 each, 1 l oil = 920 g)
are data held in the catalogue and passed in as `extra`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

BASE_UNITS = ("g", "ml", "each")

# unit -> (base unit, factor to base)
STANDARD: dict[str, tuple[str, Decimal]] = {
    "g": ("g", Decimal(1)),
    "kg": ("g", Decimal(1000)),
    "mg": ("g", Decimal("0.001")),
    "lb": ("g", Decimal("453.59237")),
    "oz": ("g", Decimal("28.349523125")),
    "ml": ("ml", Decimal(1)),
    "cl": ("ml", Decimal(10)),
    "l": ("ml", Decimal(1000)),
    "each": ("each", Decimal(1)),
    "dozen": ("each", Decimal(12)),
}

ALIASES = {
    "gram": "g", "grams": "g", "gr": "g", "grm": "g",
    "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "lbs": "lb", "pound": "lb", "pounds": "lb",
    "ltr": "l", "ltrs": "l", "litre": "l", "litres": "l", "liter": "l", "liters": "l", "lt": "l",
    "millilitre": "ml", "millilitres": "ml", "mls": "ml",
    "ea": "each", "pc": "each", "pcs": "each", "piece": "each", "pieces": "each", "unit": "each",
    "units": "each", "item": "each", "items": "each", "x": "each", "no": "each", "nr": "each",
    "doz": "dozen",
}


class UnknownConversion(ValueError):
    """No path from the invoiced unit to the ingredient's base unit (-> unmatched_unit)."""


def normalise_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    u = unit.strip().lower().rstrip(".")
    return ALIASES.get(u, u) or None


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal
    unit: str

    def to_base(self, base_unit: str, extra: dict[str, Decimal] | None = None) -> Quantity:
        return Quantity(convert(self.value, self.unit, base_unit, extra), base_unit)


def factor_to_base(unit: str, base_unit: str, extra: dict[str, Decimal] | None = None) -> Decimal:
    """Factor converting one `unit` into `base_unit`. `extra` maps unit -> base-unit factor for this
    ingredient (e.g. {"case": 6, "l": 920} for an oil sold by volume but stocked in grams)."""
    u = normalise_unit(unit)
    if u is None:
        raise UnknownConversion("missing unit")
    extra = {normalise_unit(k) or k: Decimal(v) for k, v in (extra or {}).items()}
    if u in extra:
        return extra[u]
    if u in STANDARD:
        std_base, factor = STANDARD[u]
        if std_base == base_unit:
            return factor
        # e.g. invoiced in l, stocked in g: go via a density-style conversion held in extra
        if std_base in extra:
            return factor * extra[std_base]
    raise UnknownConversion(f"no conversion from {unit!r} to {base_unit!r}")


def convert(value: Decimal, unit: str, base_unit: str, extra: dict[str, Decimal] | None = None) -> Decimal:
    return Decimal(value) * factor_to_base(unit, base_unit, extra)


_PACK = re.compile(
    r"^\s*(?:(?P<count>\d+(?:\.\d+)?)\s*[x×*]\s*)?(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z]+)?\s*$"  # noqa: RUF001
)


@dataclass(frozen=True, slots=True)
class Pack:
    """A pack expression: `count` packs of `size` `unit`, e.g. "2 x 5kg" -> (2, 5, kg)."""

    count: Decimal
    size: Decimal
    unit: str | None

    @property
    def total(self) -> Decimal:
        return self.count * self.size


def parse_pack(text: str | None) -> Pack | None:
    if not text:
        return None
    m = _PACK.match(text.replace(",", "."))
    if not m:
        return None
    try:
        count = Decimal(m["count"]) if m["count"] else Decimal(1)
        size = Decimal(m["size"])
    except InvalidOperation:
        return None
    return Pack(count=count, size=size, unit=normalise_unit(m["unit"]))


def qty_in_base(
    qty: Decimal,
    uom: str | None,
    pack_size: str | None,
    base_unit: str,
    extra: dict[str, Decimal] | None = None,
) -> Decimal:
    """Invoiced quantity converted to the ingredient base unit.

    qty=3, uom="case", pack_size="2 x 5kg", base g -> 3 x 2 x 5 x 1000 = 30000 g.
    qty=12, uom="kg", pack_size=None, base g -> 12000 g.
    """
    pack = parse_pack(pack_size)
    if pack is not None and pack.unit is not None:
        return Decimal(qty) * pack.total * factor_to_base(pack.unit, base_unit, extra)
    if pack is not None:  # pack_size "6" with uom "each"/"case": count of base units per invoiced unit
        unit = uom if normalise_unit(uom) not in (None, "case", "box", "pack", "tray", "bag") else "each"
        return Decimal(qty) * pack.total * factor_to_base(unit or "each", base_unit, extra)
    return convert(Decimal(qty), uom or "", base_unit, extra)
