"""LMDI decomposition sums to the total change (SRS §4.3)."""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.domain.menu.lmdi import decompose_revenue


@given(
    o0=st.decimals(min_value=1, max_value=500, places=2),
    s0=st.decimals(min_value=100, max_value=5000, places=2),
    o1=st.decimals(min_value=1, max_value=500, places=2),
    s1=st.decimals(min_value=100, max_value=5000, places=2),
)
def test_lmdi_parts_sum_to_total(o0, s0, o1, s1):
    _total, d_orders, d_spend = decompose_revenue(o0, s0, o1, s1)
    r0 = o0 * s0
    r1 = o1 * s1
    if r0 > 0 and r1 > 0:
        assert abs((d_orders + d_spend) - (r1 - r0)) < Decimal("0.02")
