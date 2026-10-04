"""Same-weekday median and MAD baselines (FR-ANO-02), as in v1: the same weekday over the last N weeks
(default 4); fewer than 3 points means the detector is skipped and the skip is logged."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

MAD_SCALE = Decimal("1.4826")
ZERO = Decimal(0)


def mad(values: list[Decimal]) -> Decimal:
    if len(values) < 2:
        return ZERO
    med = Decimal(str(median(values)))
    return Decimal(str(median([abs(v - med) for v in values])))


def robust_z(value: Decimal, values: list[Decimal]) -> Decimal | None:
    if len(values) < 3:
        return None
    med = Decimal(str(median(values)))
    m = mad(values)
    if m == 0:
        return ZERO if value == med else None
    return (value - med) / (MAD_SCALE * m)


def same_weekdays(day: date, weeks: int) -> list[date]:
    return [day - timedelta(weeks=i) for i in range(1, weeks + 1)]


@dataclass(frozen=True)
class Baseline:
    values: tuple[Decimal, ...]
    median: Decimal
    sigma: Decimal  # 1.4826 x MAD

    @property
    def n(self) -> int:
        return len(self.values)

    @classmethod
    def of(cls, values: list[Decimal]) -> "Baseline":
        med = Decimal(str(median(values))) if values else ZERO
        return cls(tuple(values), med, (MAD_SCALE * mad(values)).quantize(Decimal("0.0001")))

    def z(self, value: Decimal) -> Decimal | None:
        if self.sigma == 0:
            return None
        return ((value - self.median) / self.sigma).quantize(Decimal("0.01"))
