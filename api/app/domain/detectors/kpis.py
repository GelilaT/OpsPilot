"""Dashboard/brief KPIs: a day against the same weekday over the baseline weeks (median). Currency and count
deltas are in %, ratio deltas in percentage points (v1 FR rule)."""

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from app.domain.detectors.baseline import Baseline
from app.domain.detectors.data import DayFacts


class Kpi(BaseModel):
    key: str
    label: str
    unit: str  # money | pct | count
    value: float | None
    baseline: float | None
    delta: float | None
    delta_unit: str  # pct | pt
    good_when: str  # up | down


def _r(v: Decimal | None, q: str = "0.1") -> float | None:
    return None if v is None else float(v.quantize(Decimal(q), rounding=ROUND_HALF_UP))


def _ratio(num: int, f: DayFacts) -> Decimal | None:
    return Decimal(num) / Decimal(f.revenue) * 100 if f.revenue else None


def compute_kpis(today: DayFacts, base: list[DayFacts]) -> list[Kpi]:
    traded = [f for f in base if f.traded]

    def money(key: str, label: str, fn) -> Kpi:
        b = Baseline.of([Decimal(fn(f)) for f in traded]).median if traded else None
        v = Decimal(fn(today))
        return Kpi(key=key, label=label, unit="money", value=float(v), baseline=_r(b, "1"),
                   delta=_r((v - b) / b * 100) if b else None, delta_unit="pct", good_when="up")

    def count(key: str, label: str, fn) -> Kpi:
        k = money(key, label, fn)
        return k.model_copy(update={"unit": "count"})

    def ratio(key: str, label: str, fn, good_when: str) -> Kpi:
        v = fn(today)
        vals = [x for x in (fn(f) for f in traded) if x is not None]
        b = Baseline.of(vals).median if vals else None
        return Kpi(key=key, label=label, unit="pct", value=_r(v), baseline=_r(b),
                   delta=_r(v - b) if v is not None and b is not None else None, delta_unit="pt",
                   good_when=good_when)

    return [
        money("revenue", "Revenue (ex VAT)", lambda f: f.revenue),
        count("orders", "Orders", lambda f: f.orders),
        ratio("gp_pct", "GP %", lambda f: (Decimal(f.revenue - f.cogs) / f.revenue * 100) if f.revenue else None, "up"),
        ratio("food_cost_pct", "Food cost %", lambda f: _ratio(f.cogs, f), "down"),
        ratio("labour_pct", "Labour %", lambda f: _ratio(f.labour_cost, f), "down"),
    ]
