"""Restaurant profile model. A profile is pure data; the same simulator code runs any profile."""

import re
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal

COURSES = ("starter", "main", "side", "dessert", "drink")


@dataclass(frozen=True)
class RecipeLineSpec:
    ingredient: str
    quantity: Decimal
    unit: str
    waste: Decimal = Decimal(0)


_LINE = re.compile(r"^(?P<ing>[a-z_]+)\s+(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>[a-z]+)(?:@(?P<waste>\d+(?:\.\d+)?))?$")


def recipe(text: str) -> tuple[RecipeLineSpec, ...]:
    """'chicken_thigh 200g, tortilla_wraps 1each, rapeseed_oil 30ml@0.1' -> recipe lines."""
    lines = []
    for part in text.split(","):
        m = _LINE.match(part.strip())
        if not m:
            raise ValueError(f"bad recipe line {part!r}")
        lines.append(RecipeLineSpec(m["ing"], Decimal(m["qty"]), m["unit"], Decimal(m["waste"] or 0)))
    return tuple(lines)


@dataclass(frozen=True)
class MenuSpec:
    code: str
    name: str
    course: str  # starter | main | side | dessert | drink
    category: str  # display category on the menu
    price: Decimal  # gross, VAT inclusive, major units
    dayparts: tuple[str, ...]
    popularity: float
    recipe: tuple[RecipeLineSpec, ...]
    vat_rate: Decimal = Decimal("0.20")


@dataclass(frozen=True)
class SupplierSpec:
    code: str
    name: str
    vat_number: str
    address: str
    email: str
    phone: str
    categories: tuple[str, ...]  # pantry categories this supplier is the default for
    delivery_weekdays: tuple[int, ...]
    lead_time_days: int
    fill_rate: float
    sku_prefix: str
    price_factor: float = 1.0
    aliases: tuple[str, ...] = ()
    # Products offered as alternatives to another supplier's default: ingredient -> price (major units)
    alternatives: dict[str, Decimal] = field(default_factory=dict)
    zero_rated: bool = True  # UK food is zero-rated; drinks and some goods carry standard VAT


@dataclass(frozen=True)
class StaffSpec:
    ref: str
    display_name: str  # first name + last initial only (GDPR)
    role: str
    hourly_rate: Decimal
    area: str  # kitchen | floor | management


@dataclass(frozen=True)
class DaypartShape:
    name: str
    start: time
    end: time
    share: float
    peak: time


@dataclass(frozen=True)
class SiteSpec:
    code: str
    name: str
    city: str  # key into the weather fixture
    address: str
    latitude: Decimal
    longitude: Decimal
    covers: int
    orders_by_weekday: tuple[int, int, int, int, int, int, int]  # Monday..Sunday
    dayparts: tuple[DaypartShape, ...]
    staff: tuple[StaffSpec, ...]
    kitchen_staff_by_weekday: tuple[int, ...]
    floor_staff_by_weekday: tuple[int, ...]
    opening: time
    closing: time
    demand_factor: float = 1.0


@dataclass(frozen=True)
class UserSpec:
    email: str
    name: str
    role: str
    site_code: str | None  # None = all sites of the organisation


@dataclass(frozen=True)
class OrgProfile:
    slug: str
    name: str
    seed: int
    currency: str
    timezone: str
    region: str
    ingredients: tuple[str, ...]
    suppliers: tuple[SupplierSpec, ...]
    menu: tuple[MenuSpec, ...]
    sites: tuple[SiteSpec, ...]
    users: tuple[UserSpec, ...]
    # course -> daypart -> expected items per cover
    course_rates: dict[str, dict[str, float]]
    covers_distribution: dict[int, float]
    channel_mix: dict[str, float]
    discount_rate: float
    void_rate: float
    cash_share: float
    config: dict[str, object]
    stable_price_ingredients: frozenset[str] = frozenset()
    par_levels: dict[str, Decimal] = field(default_factory=dict)  # ingredient -> par in base units


@dataclass(frozen=True)
class PriceEvent:
    """From `on`, `supplier` charges `price` (major units per purchase unit) for `ingredient`."""

    org: str
    supplier: str
    ingredient: str
    on: date
    price: Decimal


@dataclass(frozen=True)
class ShortDelivery:
    """The PO line for `ingredient` delivered on `on` is ordered at `ordered` and arrives at `delivered`
    (purchase units). `upload_only` deliveries are booked into stock only when their invoice is
    uploaded and posted (the invoice PDF is generated for the demo)."""

    org: str
    site: str
    supplier: str
    ingredient: str
    on: date
    ordered: Decimal
    delivered: Decimal


@dataclass(frozen=True)
class UploadOnlyDelivery:
    org: str
    site: str
    supplier: str
    on: date
    layout: str = "classic"


@dataclass(frozen=True)
class Spoilage:
    """At close on `on`, all remaining stock of `ingredient` is binned as spoilage."""

    org: str
    site: str
    ingredient: str
    on: date


@dataclass(frozen=True)
class InvoiceNumberAnchor:
    """The delivery from `supplier` to `site` on `on` carries invoice `number` (numbers are sequential)."""

    org: str
    site: str
    supplier: str
    on: date
    prefix: str
    number: int


@dataclass(frozen=True)
class ParChange:
    org: str
    site: str
    ingredient: str
    on: date
    par: Decimal
    reason: str
