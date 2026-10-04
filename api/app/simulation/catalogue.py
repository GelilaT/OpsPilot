"""Deterministic catalogue derived from a profile: stable ids, supplier products, recipes in base units,
price series, weather and holidays. Everything here is a pure function of the profile and the date."""

import hashlib
import json
import random
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from pathlib import Path

from app.core.uom import convert
from app.simulation.pantry import PANTRY, PantryItem
from app.simulation.profile import MenuSpec, OrgProfile, SiteSpec, SupplierSpec
from app.simulation.scenarios import INVOICE_ANCHORS, PRICE_EVENTS

NAMESPACE = uuid.UUID("6f1c3a52-6a51-4c2a-9b6c-0b9a7f5e4471")
FIXTURES = Path(__file__).parent / "fixtures"
EPOCH = date(2026, 1, 5)  # a Monday; invoice numbers count supplier delivery days from here


def sid(*parts: object) -> uuid.UUID:
    """Stable id for a seeded entity, so re-seeding and the simulator agree on identities."""
    return uuid.uuid5(NAMESPACE, ":".join(str(p) for p in parts))


def rng(*parts: object) -> random.Random:
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def q2(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Product:
    id: uuid.UUID
    supplier: str
    ingredient: str
    sku: str
    name: str
    purchase_unit: str
    pack_size: str | None
    base_qty_per_unit: Decimal
    base_price: Decimal  # major units per purchase unit at the start of the simulation
    vat_rate: Decimal
    is_default: bool


@dataclass(frozen=True)
class RecipeUse:
    ingredient: str
    qty_base_per_portion: Decimal


class Catalogue:
    def __init__(self, org: OrgProfile) -> None:
        self.org = org
        self.org_id = sid(org.slug, "organisation")
        self.suppliers: dict[str, SupplierSpec] = {s.code: s for s in org.suppliers}
        self.supplier_ids = {s.code: sid(org.slug, "supplier", s.code) for s in org.suppliers}
        self.ingredients: dict[str, PantryItem] = {c: PANTRY[c] for c in org.ingredients}
        self.ingredient_ids = {c: sid(org.slug, "ingredient", c) for c in org.ingredients}
        self.menu: dict[str, MenuSpec] = {mi.code: mi for mi in org.menu}
        self.menu_ids = {mi.code: sid(org.slug, "menu_item", mi.code) for mi in org.menu}
        self.default_supplier: dict[str, str] = {}
        for code, item in self.ingredients.items():
            for s in org.suppliers:
                if item.category in s.categories:
                    self.default_supplier[code] = s.code
                    break
        self.products: dict[tuple[str, str], Product] = {}
        for s in org.suppliers:
            offered = [c for c in org.ingredients if self.default_supplier[c] == s.code] + list(s.alternatives)
            for i, code in enumerate(offered, start=1):
                item = PANTRY[code]
                base = s.alternatives.get(code, (item.price * Decimal(str(s.price_factor))).quantize(Decimal("0.01")))
                # UK: food is zero-rated; soft drinks, alcohol and coffee carry the standard rate.
                vat = Decimal("0.20") if item.category == "drinks" else Decimal(0)
                self.products[(s.code, code)] = Product(
                    id=sid(org.slug, "supplier_product", s.code, code), supplier=s.code, ingredient=code,
                    sku=f"{s.sku_prefix}{1000 + i * 7}", name=item.name, purchase_unit=item.purchase_unit,
                    pack_size=item.pack_size, base_qty_per_unit=item.base_qty_per_unit, base_price=base,
                    vat_rate=vat, is_default=self.default_supplier[code] == s.code and code not in s.alternatives,
                )
        self.recipes: dict[str, list[RecipeUse]] = {
            mi.code: [RecipeUse(line.ingredient, convert(line.quantity, line.unit,
                                                         self.ingredients[line.ingredient].base_unit,
                                                         self.ingredients[line.ingredient].conversions)
                                * (1 + line.waste))
                      for line in mi.recipe]
            for mi in org.menu
        }
        self._events = sorted((e for e in PRICE_EVENTS if e.org == org.slug), key=lambda e: e.on)

    # ---- ids -----------------------------------------------------------------------------------
    def site_id(self, site: SiteSpec) -> uuid.UUID:
        return sid(self.org.slug, "site", site.code)

    def default_product(self, ingredient: str) -> Product:
        return self.products[(self.default_supplier[ingredient], ingredient)]

    # ---- prices --------------------------------------------------------------------------------
    def price_minor(self, supplier: str, ingredient: str, day: date) -> int:
        """Price per purchase unit on `day`, in minor units."""
        product = self.products[(supplier, ingredient)]
        price = product.base_price
        if ingredient not in self.org.stable_price_ingredients and ingredient not in self.suppliers[supplier].alternatives:
            month = date(2026, 2, 1)
            while month <= day:
                drift = Decimal(str(round(rng(self.org.slug, "drift", supplier, ingredient, month).uniform(-0.012, 0.02), 4)))
                price = price * (1 + drift)
                month = (month + timedelta(days=32)).replace(day=1)
        for event in self._events:
            if event.supplier == supplier and event.ingredient == ingredient and event.on <= day:
                price = event.price
        return q2(price * 100)

    def price_per_base_minor(self, supplier: str, ingredient: str, day: date) -> Decimal:
        product = self.products[(supplier, ingredient)]
        return Decimal(self.price_minor(supplier, ingredient, day)) / product.base_qty_per_unit

    # ---- invoice numbering ---------------------------------------------------------------------
    def invoice_number(self, site: SiteSpec, supplier: str, day: date) -> str:
        spec = self.suppliers[supplier]
        index = sum(1 for n in range((day - EPOCH).days) if (EPOCH + timedelta(n)).weekday() in spec.delivery_weekdays)
        for anchor in INVOICE_ANCHORS:
            if anchor.org == self.org.slug and anchor.site == site.code and anchor.supplier == supplier:
                anchor_index = sum(1 for n in range((anchor.on - EPOCH).days)
                                   if (EPOCH + timedelta(n)).weekday() in spec.delivery_weekdays)
                return f"{anchor.prefix}{anchor.number + index - anchor_index}"
        base = rng(self.org.slug, site.code, supplier, "invoice-base").randint(10_000, 80_000)
        styles = {0: "{n}", 1: "SI-{n}", 2: "{p}/{n}", 3: "INV{n}"}
        style = styles[rng(self.org.slug, supplier, "invoice-style").randint(0, 3)]
        return style.format(n=base + index, p=spec.code)

    def po_number(self, site: SiteSpec, supplier: str, delivery: date) -> str:
        return f"PO-{site.code}-{delivery:%y%m%d}-{supplier}"


@cache
def _weather() -> dict:
    return json.loads((FIXTURES / "weather.json").read_text())


@cache
def _holidays() -> dict:
    return json.loads((FIXTURES / "bank_holidays.json").read_text())


@dataclass(frozen=True)
class Weather:
    temp_max: Decimal
    temp_min: Decimal
    precipitation: Decimal
    source: str


_CLIMATE = {1: 7, 2: 8, 3: 10, 4: 13, 5: 16, 6: 19, 7: 21, 8: 20, 9: 18, 10: 14, 11: 10, 12: 8}


def weather(city: str, day: date) -> Weather:
    """Real Open-Meteo history from the fixture; deterministic climatology outside its range."""
    rec = _weather().get(city, {}).get("days", {}).get(day.isoformat())
    if rec:
        return Weather(Decimal(str(rec[0])), Decimal(str(rec[1])), Decimal(str(rec[2])), "archive")
    r = rng("climate", city, day)
    hi = _CLIMATE[day.month] + r.gauss(0, 2.5)
    rain = max(0.0, r.gauss(1.5, 4)) if r.random() < 0.55 else 0.0
    return Weather(Decimal(str(round(hi, 1))), Decimal(str(round(hi - 7 - r.random() * 2, 1))),
                   Decimal(str(round(rain, 1))), "climatology")


def bank_holiday(region: str, day: date) -> str | None:
    for event in _holidays().get(region, []):
        if event["date"] == day.isoformat():
            return event["title"]
    return None


def holidays(region: str) -> list[tuple[date, str]]:
    return [(date.fromisoformat(e["date"]), e["title"]) for e in _holidays().get(region, [])]
