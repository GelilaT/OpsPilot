"""Money in minor units and UoM conversion (SRS Test Strategy: unit + property-based)."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.money import Money
from app.core.uom import UnknownConversion, convert, parse_pack, qty_in_base


def test_money_from_decimal_rounds_half_up():
    assert Money.from_decimal("7.905", "GBP").minor == 791
    assert Money.from_decimal("1234", "JPY").minor == 1234


def test_money_currency_mismatch():
    with pytest.raises(ValueError):
        Money(100, "GBP") + Money(100, "EUR")


def test_money_rejects_floats_and_unknown_currency():
    with pytest.raises(TypeError):
        Money(1.5, "GBP")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Money(1, "XXX")


def test_money_format():
    assert Money(-123456, "GBP").format() == "-£1,234.56"


@given(st.integers(-10**12, 10**12), st.integers(-10**12, 10**12))
def test_money_addition_is_exact(a, b):
    assert (Money(a, "GBP") + Money(b, "GBP")).minor == a + b
    assert (Money(a, "GBP") + Money(b, "GBP") - Money(b, "GBP")).minor == a


@given(st.integers(0, 10**9), st.lists(st.integers(1, 1000), min_size=1, max_size=12))
def test_allocate_parts_sum_exactly(total, weights):
    parts = Money(total, "GBP").allocate([Decimal(w) for w in weights])
    assert sum(p.minor for p in parts) == total
    assert all(p.minor >= 0 for p in parts)


@pytest.mark.parametrize(("qty", "uom", "pack", "base", "expected"), [
    ("12", "kg", None, "g", "12000"),
    ("2", "case", "2 x 5kg", "g", "20000"),
    ("3", "case", "6", "each", "18"),
    ("1", "each", "2x5kg", "g", "10000"),
    ("4", "l", None, "ml", "4000"),
    ("2", "Kgs", None, "g", "2000"),
    ("1", "dozen", None, "each", "12"),
])
def test_qty_in_base(qty, uom, pack, base, expected):
    assert qty_in_base(Decimal(qty), uom, pack, base) == Decimal(expected)


def test_unknown_conversion_raises():
    with pytest.raises(UnknownConversion):
        qty_in_base(Decimal(1), "case", None, "g")
    with pytest.raises(UnknownConversion):
        convert(Decimal(1), "l", "g")


def test_ingredient_specific_conversion():
    # fryer oil invoiced in litres, stocked in grams (density 920 g/l)
    assert convert(Decimal(20), "l", "g", {"ml": Decimal("0.92")}) == Decimal("18400.00")
    assert qty_in_base(Decimal(2), "case", None, "each", {"case": Decimal(6)}) == Decimal(12)


def test_parse_pack():
    p = parse_pack("2 x 5kg")
    assert p and p.count == 2 and p.size == 5 and p.unit == "kg"
    assert parse_pack("rubbish") is None


units = st.sampled_from([("kg", "g"), ("lb", "g"), ("oz", "g"), ("l", "ml"), ("cl", "ml"), ("dozen", "each")])


@given(units, st.decimals(min_value=Decimal("0.001"), max_value=Decimal(100000), places=3))
def test_conversion_round_trip(pair, value):
    unit, base = pair
    there = convert(value, unit, base)
    back = there / convert(Decimal(1), unit, base)
    assert abs(back - value) < Decimal("1e-9")
