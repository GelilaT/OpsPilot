"""Log-mean Divisia index decomposition (SRS 4.3). Parts sum exactly to the total change.

    R = O x S                      revenue = orders x average spend
    L(a, b) = (a - b) / (ln a - ln b)
    dR_orders = L(R1, R0) ln(O1 / O0);  dR_spend = L(R1, R0) ln(S1 / S0)

The spend change is split per item into a price effect (units per order now x price change) and a mix
effect (change in units per order x old price); both are scaled to dR_spend so every part adds up.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from math import log

ZERO = Decimal(0)


def log_mean(a: Decimal, b: Decimal) -> Decimal:
    if a == b:
        return a
    if a <= 0 or b <= 0:
        return ZERO
    denom = Decimal(str(log(float(a)) - log(float(b))))
    return (a - b) / denom if denom else a


def decompose_revenue(orders0: Decimal, spend0: Decimal, orders1: Decimal, spend1: Decimal,
                      ) -> tuple[Decimal, Decimal, Decimal]:
    """(total_delta, delta_orders, delta_spend) with delta_orders + delta_spend == total_delta exactly."""
    r0, r1 = orders0 * spend0, orders1 * spend1
    total = r1 - r0
    if r0 <= 0 or r1 <= 0 or orders0 <= 0 or orders1 <= 0 or spend0 <= 0 or spend1 <= 0:
        return total, total, ZERO
    lm = log_mean(r1, r0)
    d_orders = lm * Decimal(str(log(float(orders1 / orders0))))
    return total, d_orders, total - d_orders  # the spend part absorbs float rounding, so parts sum exactly


@dataclass(frozen=True)
class ItemEffect:
    menu_item_id: uuid.UUID
    units0: Decimal  # baseline units (mean per day)
    units1: Decimal
    contribution: Decimal  # share of dR_spend
    price_effect: Decimal
    mix_effect: Decimal


@dataclass(frozen=True)
class SpendSplit:
    price_effect: Decimal
    mix_effect: Decimal
    items: list[ItemEffect]


def split_spend(d_spend: Decimal, orders0: Decimal, orders1: Decimal,
                base: dict[uuid.UUID, tuple[Decimal, Decimal]], now: dict[uuid.UUID, tuple[Decimal, Decimal]],
                ) -> SpendSplit:
    """`base`/`now`: item -> (units, revenue). Item contribution_i = u1 p1 - u0 p0 (per order), price and mix
    effects per item, all scaled so that their sums equal `d_spend` exactly."""
    raw: dict[uuid.UUID, tuple[Decimal, Decimal, Decimal, Decimal, Decimal]] = {}
    for item in set(base) | set(now):
        u0, r0 = base.get(item, (ZERO, ZERO))
        u1, r1 = now.get(item, (ZERO, ZERO))
        p0 = r0 / u0 if u0 else (r1 / u1 if u1 else ZERO)
        p1 = r1 / u1 if u1 else p0
        a0 = u0 / orders0 if orders0 else ZERO
        a1 = u1 / orders1 if orders1 else ZERO
        price = a1 * (p1 - p0)
        mix = (a1 - a0) * p0
        raw[item] = (u0, u1, price + mix, price, mix)
    total = sum((v[2] for v in raw.values()), ZERO)
    scale = d_spend / total if total else ZERO
    items = [ItemEffect(i, v[0], v[1], v[2] * scale, v[3] * scale, v[4] * scale) for i, v in raw.items()]
    price = sum((i.price_effect for i in items), ZERO)
    return SpendSplit(price, d_spend - price, sorted(items, key=lambda i: i.contribution))


def concentration(segments: dict[str, Decimal]) -> tuple[str | None, Decimal]:
    """The segment holding the largest share of the (negative) change, and that share (0..1)."""
    negative = {k: -v for k, v in segments.items() if v < 0}
    total = sum(negative.values(), ZERO)
    if total <= 0:
        return None, ZERO
    key = max(negative, key=lambda k: negative[k])
    return key, negative[key] / total
