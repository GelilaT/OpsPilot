"""PosPort: point-of-sale data in canonical form (FR-ING-04)."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CanonicalSaleLine:
    external_item_id: str
    name: str
    quantity: Decimal
    unit_price_minor: int  # gross (VAT inclusive) menu price
    vat_rate: Decimal
    discount_minor: int = 0
    void_quantity: Decimal = Decimal(0)
    void_reason: str | None = None


@dataclass(frozen=True)
class CanonicalSale:
    external_order_id: str
    business_date: date
    opened_at: datetime
    closed_at: datetime
    covers: int
    channel: str  # dine_in, takeaway, delivery
    currency: str
    lines: tuple[CanonicalSaleLine, ...]
    discount_reason: str | None = None


@dataclass(frozen=True)
class CanonicalShift:
    external_shift_id: str
    business_date: date
    staff_ref: str
    staff_display_name: str  # first name + last initial
    role: str
    starts_at: datetime
    ends_at: datetime
    hourly_rate_minor: int


@dataclass(frozen=True)
class CanonicalCashUp:
    business_date: date
    expected_cash_minor: int
    counted_cash_minor: int
    card_total_minor: int = 0


@dataclass(frozen=True)
class PosDay:
    business_date: date
    sales: tuple[CanonicalSale, ...] = field(default_factory=tuple)
    shifts: tuple[CanonicalShift, ...] = field(default_factory=tuple)
    cash_ups: tuple[CanonicalCashUp, ...] = field(default_factory=tuple)


@runtime_checkable
class PosPort(Protocol):
    provider: str

    async def fetch_sales(self, day: date) -> list[CanonicalSale]: ...

    async def fetch_shifts(self, day: date) -> list[CanonicalShift]: ...

    async def fetch_cash_ups(self, day: date) -> list[CanonicalCashUp]: ...
