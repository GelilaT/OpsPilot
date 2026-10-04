"""Money as integer minor units with an ISO 4217 currency (SRS 2.4 Standards)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# ISO 4217 minor-unit exponents for currencies we accept; anything else is rejected by validation.
CURRENCY_EXPONENT: dict[str, int] = {
    "GBP": 2, "EUR": 2, "USD": 2, "CHF": 2, "SEK": 2, "NOK": 2, "DKK": 2, "PLN": 2, "CZK": 2,
    "CAD": 2, "AUD": 2, "NZD": 2, "ZAR": 2, "ETB": 2, "KES": 2, "AED": 2, "INR": 2, "JPY": 0, "KRW": 0,
}


def is_iso_currency(code: str | None) -> bool:
    return bool(code) and code in CURRENCY_EXPONENT


def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Money:
    minor: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.minor, int) or isinstance(self.minor, bool):
            raise TypeError("Money.minor must be an int (minor units)")
        if self.currency not in CURRENCY_EXPONENT:
            raise ValueError(f"Unsupported currency {self.currency!r}")

    @property
    def exponent(self) -> int:
        return CURRENCY_EXPONENT[self.currency]

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(0, currency)

    @classmethod
    def from_decimal(cls, amount: Decimal | str | int, currency: str) -> Money:
        exp = CURRENCY_EXPONENT[currency]
        return cls(int(round_half_up(Decimal(amount) * (10**exp))), currency)

    def to_decimal(self) -> Decimal:
        return Decimal(self.minor).scaleb(-self.exponent)

    def _check(self, other: Money) -> None:
        if other.currency != self.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.minor - other.minor, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.minor, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.minor < other.minor

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.minor <= other.minor

    def times(self, factor: Decimal | int | str) -> Money:
        """Multiply by a quantity or rate, rounding half-up to the minor unit."""
        return Money(int(round_half_up(Decimal(self.minor) * Decimal(factor))), self.currency)

    def allocate(self, weights: list[Decimal]) -> list[Money]:
        """Split into parts proportional to weights that sum exactly to self (largest remainder)."""
        total = sum(weights, Decimal(0))
        if total <= 0:
            raise ValueError("weights must sum to a positive number")
        raw = [Decimal(self.minor) * w / total for w in weights]
        floors = [int(r.to_integral_value(rounding="ROUND_FLOOR")) for r in raw]
        remainder = self.minor - sum(floors)
        order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
        for i in order[:remainder]:
            floors[i] += 1
        return [Money(f, self.currency) for f in floors]

    def format(self) -> str:
        symbol = {"GBP": "£", "EUR": "€", "USD": "$"}.get(self.currency, self.currency + " ")
        sign = "-" if self.minor < 0 else ""
        return f"{sign}{symbol}{abs(self.to_decimal()):,.{self.exponent}f}"

    def __str__(self) -> str:
        return self.format()
