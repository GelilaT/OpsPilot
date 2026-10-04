"""One simulated restaurant site, stepped a day at a time.

The engine is pure Python over a small state (stock on hand, weighted average cost, open purchase
orders, par levels). The seed runs it for 120 days in memory; "simulate next day" loads the state from
the database and runs one more day. Sales respect stock: when an ingredient runs out, dishes that need
it stop selling (this is how S2's Friday stock-out emerges rather than being drawn in).
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal
from zoneinfo import ZoneInfo

from app.domain.inventory.rules import new_wac
from app.ports.pos import CanonicalCashUp, CanonicalSale, CanonicalSaleLine, CanonicalShift
from app.simulation.catalogue import Catalogue, bank_holiday, q2, rng, sid, weather
from app.simulation.profile import COURSES, DaypartShape, OrgProfile, SiteSpec
from app.simulation.scenarios import PAR_CHANGES, SHORT_DELIVERIES, SPOILAGE, UPLOAD_ONLY

ZERO = Decimal(0)
SAFETY_DAYS = Decimal("0.5")
ORDER_BUFFER = Decimal("1.25")
WALK_OUT_RATE = 0.35  # parties that leave when a guest cannot get the main they wanted
LABOUR_ON_COST = Decimal("1.30")  # employer NI, pension and holiday on top of the hourly rate


# ---------------------------------------------------------------------------------------------------
# State and results
# ---------------------------------------------------------------------------------------------------
@dataclass
class POLineState:
    id: str
    ingredient: str
    supplier_product_id: str
    qty_units: Decimal
    qty_base: Decimal
    unit_price_minor: int


@dataclass
class POState:
    id: str
    number: str
    supplier: str
    order_date: date
    delivery_date: date
    lines: list[POLineState]
    status: str = "sent"


@dataclass
class WorldState:
    on_hand: dict[str, Decimal]
    wac: dict[str, Decimal]  # minor units per base unit
    open_pos: list[POState] = field(default_factory=list)
    par: dict[str, Decimal] = field(default_factory=dict)
    suppliers: dict[str, str] = field(default_factory=dict)  # ingredient -> supplier code chosen by the site
    receipts_today: list[tuple[datetime, str, Decimal]] = field(default_factory=list)


@dataclass
class DeliveredLine:
    po_line_id: str | None
    ingredient: str
    supplier_product_id: str
    ordered_units: Decimal
    delivered_units: Decimal
    delivered_base: Decimal
    unit_price_minor: int  # invoiced price per purchase unit
    price_per_base_minor: Decimal
    vat_rate: Decimal


@dataclass
class Delivery:
    supplier: str
    po_id: str | None
    po_number: str | None
    business_date: date
    received_at: datetime
    invoice_number: str
    upload_only: bool
    layout: str
    lines: list[DeliveredLine]
    wac_after: dict[str, Decimal] = field(default_factory=dict)
    seq: int = 0  # a second PO from the same supplier that day arrives as its own delivery and invoice


@dataclass
class Movement:
    ingredient: str
    at: datetime
    business_date: date
    type: str
    qty_base: Decimal
    unit_cost_minor: Decimal
    ref_type: str
    ref_id: str


@dataclass
class WasteRecord:
    ingredient: str
    at: datetime
    qty_base: Decimal
    reason: str
    cost_minor: int
    note: str | None = None


@dataclass
class CountRecord:
    counted_at: datetime
    lines: list[tuple[str, Decimal, Decimal]]  # ingredient, counted, ledger


@dataclass
class EndOfDay:
    movements: list[Movement]
    waste: list[WasteRecord]
    count: CountRecord | None


@dataclass
class PlannedPO:
    po: POState
    site_code: str


# ---------------------------------------------------------------------------------------------------
# Availability tracking during service
# ---------------------------------------------------------------------------------------------------
class StockTracker:
    def __init__(self, opening: dict[str, Decimal], receipts: list[tuple[datetime, str, Decimal]]) -> None:
        self.on_hand = defaultdict(Decimal, opening)
        self.pending = sorted(receipts, key=lambda r: r[0])
        self.stock_out_at: dict[str, datetime] = {}

    def advance(self, at: datetime) -> None:
        while self.pending and self.pending[0][0] <= at:
            _, ing, qty = self.pending.pop(0)
            self.on_hand[ing] += qty

    def can_make(self, uses, at: datetime) -> bool:
        self.advance(at)
        ok = all(self.on_hand[u.ingredient] >= u.qty_base_per_portion for u in uses)
        if not ok:
            for u in uses:
                if self.on_hand[u.ingredient] < u.qty_base_per_portion:
                    self.stock_out_at.setdefault(u.ingredient, at)
        return ok

    def take(self, uses) -> None:
        for u in uses:
            self.on_hand[u.ingredient] -= u.qty_base_per_portion

    def give_back(self, uses) -> None:
        for u in uses:
            self.on_hand[u.ingredient] += u.qty_base_per_portion


# ---------------------------------------------------------------------------------------------------
# The site simulator
# ---------------------------------------------------------------------------------------------------
class SiteWorld:
    def __init__(self, org: OrgProfile, site: SiteSpec, catalogue: Catalogue, state: WorldState) -> None:
        self.org, self.site, self.cat, self.state = org, site, catalogue, state
        self.tz = ZoneInfo(org.timezone)
        self.site_id = catalogue.site_id(site)
        self._dayparts = {d.name: d for d in site.dayparts}
        self._mean_covers = sum(k * p for k, p in org.covers_distribution.items())

    # ---- helpers -------------------------------------------------------------------------------
    def at(self, day: date, t: time) -> datetime:
        return datetime.combine(day, t, tzinfo=self.tz)

    def _items(self, course: str, daypart: str):
        return [mi for mi in self.org.menu if mi.course == course and daypart in mi.dayparts]

    def demand_factor(self, day: date) -> float:
        """Weather, bank holiday and trend multipliers applied to the weekday baseline."""
        w = weather(self.site.city, day)
        temp, rain = float(w.temp_max), float(w.precipitation)
        f = 1.0
        if temp < 10:
            f *= 0.95
        elif temp >= 23:
            f *= 1.10 if day.weekday() >= 5 else 1.06
        elif temp >= 18:
            f *= 1.03
        if rain > 15:
            f *= 0.88
        elif rain > 5:
            f *= 0.94
        if bank_holiday(self.org.region, day):
            f *= 1.18
        f *= 1 + 0.0004 * (day - date(2026, 6, 1)).days  # gentle growth
        return f * self.site.demand_factor

    def expected_portions(self, day: date) -> dict[str, float]:
        """The kitchen's expectation for ordering (weekday + bank holiday, no weather, no noise)."""
        orders = self.site.orders_by_weekday[day.weekday()] * self.site.demand_factor
        if bank_holiday(self.org.region, day):
            orders *= 1.18
        out: dict[str, float] = defaultdict(float)
        for dp in self.site.dayparts:
            n = orders * dp.share * self._mean_covers
            for course in COURSES:
                items = self._items(course, dp.name)
                total = sum(mi.popularity for mi in items)
                rate = self.org.course_rates[course][dp.name]
                for mi in items:
                    out[mi.code] += n * rate * mi.popularity / total
        return out

    def expected_usage(self, day: date) -> dict[str, Decimal]:
        usage: dict[str, Decimal] = defaultdict(Decimal)
        for item, portions in self.expected_portions(day).items():
            for use in self.cat.recipes[item]:
                usage[use.ingredient] += use.qty_base_per_portion * Decimal(str(portions))
        return usage

    # ---- deliveries ------------------------------------------------------------------------------
    def deliveries(self, day: date) -> list[Delivery]:
        """Deliver every open PO due today. Receipts update stock and WAC unless the delivery is
        upload-only (then the invoice must be uploaded and posted to book it)."""
        out: list[Delivery] = []
        due = [po for po in self.state.open_pos if po.delivery_date == day]
        self.state.open_pos = [po for po in self.state.open_pos if po.delivery_date != day]
        seen: dict[str, int] = defaultdict(int)
        for po in due:
            seq = seen[po.supplier]
            seen[po.supplier] += 1
            spec = self.cat.suppliers[po.supplier]
            r = rng(self.org.slug, self.site.code, "delivery", po.number)
            received_at = self.at(day, time(7, 0)) + timedelta(minutes=r.randint(0, 120))
            upload = next((u for u in UPLOAD_ONLY if u.org == self.org.slug and u.site == self.site.code
                           and u.supplier == po.supplier and u.on == day), None)
            lines: list[DeliveredLine] = []
            for line in po.lines:
                short = next((s for s in SHORT_DELIVERIES if s.org == self.org.slug and s.site == self.site.code
                              and s.supplier == po.supplier and s.ingredient == line.ingredient and s.on == day), None)
                # A short line arrives at 60-90% (75% on average), so a supplier with fill rate f shorts
                # (1 - f) / 0.25 of its lines; the quantity-weighted fill rate then averages f.
                short_probability = min(0.9, (1 - spec.fill_rate) / 0.25)
                if short is not None:
                    delivered = short.delivered
                elif r.random() >= short_probability:
                    delivered = line.qty_units
                else:
                    delivered = (line.qty_units * Decimal(str(r.uniform(0.6, 0.9)))).to_integral_value()
                product = self.cat.products[(po.supplier, line.ingredient)]
                price = self.cat.price_minor(po.supplier, line.ingredient, day)
                lines.append(DeliveredLine(
                    po_line_id=line.id, ingredient=line.ingredient, supplier_product_id=str(product.id),
                    ordered_units=line.qty_units, delivered_units=delivered,
                    delivered_base=delivered * product.base_qty_per_unit, unit_price_minor=price,
                    price_per_base_minor=Decimal(price) / product.base_qty_per_unit, vat_rate=product.vat_rate,
                ))
            delivery = Delivery(
                supplier=po.supplier, po_id=po.id, po_number=po.number, business_date=day, received_at=received_at,
                invoice_number=self.cat.invoice_number(self.site, po.supplier, day) + (f"-{seq + 1}" if seq else ""),
                upload_only=upload is not None and seq == 0, layout=upload.layout if upload and seq == 0 else "classic",
                lines=lines, seq=seq,
            )
            if not delivery.upload_only:
                for dl in lines:
                    if dl.delivered_base > 0:
                        self.receive(dl.ingredient, dl.delivered_base, dl.price_per_base_minor, received_at)
                        delivery.wac_after[dl.ingredient] = self.state.wac[dl.ingredient]
            out.append(delivery)
        return out

    def receive(self, ingredient: str, qty_base: Decimal, price_per_base: Decimal, at: datetime) -> None:
        """Book a receipt: weighted average cost update (FR-STK-09)."""
        on_hand = self.state.on_hand.get(ingredient, ZERO)
        wac = self.state.wac.get(ingredient, price_per_base)
        self.state.wac[ingredient] = new_wac(on_hand, wac, qty_base, price_per_base)
        self.state.on_hand[ingredient] = self.state.on_hand.get(ingredient, ZERO) + qty_base
        self.state.receipts_today.append((at, ingredient, qty_base))

    # ---- sales -----------------------------------------------------------------------------------
    def sales(self, day: date, opening: dict[str, Decimal] | None = None,
              receipts: list[tuple[datetime, str, Decimal]] | None = None) -> tuple[list[CanonicalSale], StockTracker]:
        """Orders for the day, generated chronologically against available stock.

        `opening` / `receipts` default to the in-memory state (seed); the POS simulator adapter passes
        the ledger's view instead.
        """
        if opening is None:
            start_of_day = self.state.receipts_today
            opening = {k: v - sum(q for _, i, q in start_of_day if i == k) for k, v in self.state.on_hand.items()}
            receipts = list(start_of_day)
        tracker = StockTracker(opening, receipts or [])
        r = rng(self.org.slug, self.site.code, "sales", day)
        factor = self.demand_factor(day) * math.exp(r.gauss(0, 0.07))
        base_orders = self.site.orders_by_weekday[day.weekday()]
        planned: list[tuple[datetime, DaypartShape]] = []
        for dp in self.site.dayparts:
            expected = base_orders * dp.share * factor
            n = max(0, round(r.gauss(expected, math.sqrt(max(expected, 1)) * 0.6)))
            start, end, peak = (t.hour * 3600 + t.minute * 60 for t in (dp.start, dp.end, dp.peak))
            midnight = self.at(day, time(0))
            for _ in range(n):
                seconds = int(r.triangular(start, end, peak))
                planned.append((midnight + timedelta(seconds=seconds), dp))
        planned.sort(key=lambda p: p[0])

        covers_k = list(self.org.covers_distribution)
        covers_w = list(self.org.covers_distribution.values())
        channels = list(self.org.channel_mix)
        channel_w = list(self.org.channel_mix.values())
        sales: list[CanonicalSale] = []
        for seq, (opened_at, dp) in enumerate(planned, start=1):
            orr = rng(self.org.slug, self.site.code, "order", day, seq)
            covers = orr.choices(covers_k, covers_w)[0]
            channel = orr.choices(channels, channel_w)[0]
            if channel != "dine_in":
                covers = min(covers, 2)
            basket: dict[str, int] = defaultdict(int)
            disappointed = False
            for _ in range(covers):
                for course in COURSES:
                    rate = self.org.course_rates[course][dp.name]
                    if channel != "dine_in" and course in ("starter", "drink"):
                        rate *= 0.4
                    count = int(rate) + (1 if orr.random() < rate - int(rate) else 0)
                    left_without = False
                    for _ in range(count):
                        items = self._items(course, dp.name)
                        if not items:
                            break
                        choice = orr.choices(items, [mi.popularity for mi in items])[0]
                        uses = self.cat.recipes[choice.code]
                        if tracker.can_make(uses, opened_at):
                            tracker.take(uses)
                            basket[choice.code] += 1
                            continue
                        if course == "main":
                            # 25% pick another available main; otherwise this guest orders nothing else.
                            alternatives = [mi for mi in items if mi.code != choice.code
                                            and tracker.can_make(self.cat.recipes[mi.code], opened_at)]
                            if alternatives and orr.random() < 0.25:
                                alt = orr.choices(alternatives, [mi.popularity for mi in alternatives])[0]
                                tracker.take(self.cat.recipes[alt.code])
                                basket[alt.code] += 1
                            else:
                                left_without = True
                                break
                    if left_without:
                        disappointed = True
                        break
            if disappointed and orr.random() < WALK_OUT_RATE:
                for code, qty in basket.items():  # the whole party leaves; nothing was cooked
                    for _ in range(qty):
                        tracker.give_back(self.cat.recipes[code])
                basket.clear()
            if not basket:
                continue  # walk-out: the order never reaches the till
            lines = []
            for code, qty in sorted(basket.items()):
                mi = self.cat.menu[code]
                void_q = 1 if orr.random() < self.org.void_rate else 0
                lines.append(CanonicalSaleLine(
                    external_item_id=f"SIM-{code}", name=mi.name, quantity=Decimal(qty - void_q),
                    unit_price_minor=self.menu_price_minor(code, day), vat_rate=mi.vat_rate,
                    void_quantity=Decimal(void_q), void_reason="kitchen error" if void_q else None,
                ))
            gross = sum(int(line.quantity) * line.unit_price_minor for line in lines)
            discount_reason = None
            if orr.random() < self.org.discount_rate and gross > 0:
                staff = orr.random() < 0.15
                discount_reason = "staff" if staff else "loyalty"
                pct = Decimal("0.5") if staff else Decimal("0.1")
                lines = self._apply_discount(lines, pct)
            duration = orr.randint(45, 100) if channel == "dine_in" else orr.randint(8, 20)
            sales.append(CanonicalSale(
                external_order_id=f"{self.site.code}-{day:%Y%m%d}-{seq:04d}", business_date=day,
                opened_at=opened_at, closed_at=opened_at + timedelta(minutes=duration), covers=covers,
                channel=channel, currency=self.org.currency, lines=tuple(lines), discount_reason=discount_reason,
            ))
        return sales, tracker

    @staticmethod
    def _apply_discount(lines, pct: Decimal):
        out = []
        for line in lines:
            line_gross = int(line.quantity) * line.unit_price_minor
            out.append(CanonicalSaleLine(
                external_item_id=line.external_item_id, name=line.name, quantity=line.quantity,
                unit_price_minor=line.unit_price_minor, vat_rate=line.vat_rate,
                discount_minor=q2(Decimal(line_gross) * pct), void_quantity=line.void_quantity,
                void_reason=line.void_reason,
            ))
        return out

    def menu_price_minor(self, code: str, day: date) -> int:
        return q2(self.cat.menu[code].price * 100)

    # ---- labour and cash ---------------------------------------------------------------------------
    def shifts(self, day: date) -> list[CanonicalShift]:
        r = rng(self.org.slug, self.site.code, "rota", day)
        wd = day.weekday()
        out: list[CanonicalShift] = []
        open_dt = self.at(day, self.site.opening)
        close_dt = self.at(day, self.site.closing)
        mid = open_dt + (close_dt - open_dt) / 2

        def add(staff, start: datetime, end: datetime):
            hours = Decimal(str(round((end - start).total_seconds() / 3600, 2)))
            out.append(CanonicalShift(
                external_shift_id=f"{self.site.code}-{day:%Y%m%d}-{len(out):02d}-{staff.ref}", business_date=day,
                staff_ref=staff.ref, staff_display_name=staff.display_name, role=staff.role, starts_at=start,
                ends_at=end, hourly_rate_minor=q2(staff.hourly_rate * LABOUR_ON_COST * 100),
            ))
            return hours

        for area, needed in (("kitchen", self.site.kitchen_staff_by_weekday[wd]),
                             ("floor", self.site.floor_staff_by_weekday[wd])):
            pool = [s for s in self.site.staff if s.area == area]
            r.shuffle(pool)
            for i in range(needed):
                staff = pool[i % len(pool)]
                early = i % 2 == 0
                prep = timedelta(hours=1, minutes=30) if area == "kitchen" else timedelta(minutes=30)
                if early:
                    add(staff, open_dt - prep, mid + timedelta(hours=1))
                else:
                    add(staff, mid - timedelta(hours=1), close_dt + timedelta(minutes=45))
        managers = [s for s in self.site.staff if s.area == "management"]
        if managers:
            manager = managers[0] if wd not in (0, 1) else managers[-1]
            add(manager, open_dt - timedelta(hours=1), close_dt - timedelta(hours=3) if wd < 4 else close_dt)
        return out

    def cash_up(self, day: date, sales: list[CanonicalSale]) -> CanonicalCashUp:
        r = rng(self.org.slug, self.site.code, "cash", day)
        cash = card = 0
        for sale in sales:
            net = sum(int(line.quantity) * line.unit_price_minor - line.discount_minor for line in sale.lines)
            if sale.channel != "delivery" and rng(sale.external_order_id, "pay").random() < self.org.cash_share:
                cash += net
            else:
                card += net
        variance = round(r.gauss(0, 150) / 10) * 10
        if r.random() < 0.02:
            variance -= r.choice([1000, 2000, 2500])
        return CanonicalCashUp(day, cash, cash + variance, card)

    # ---- end of day ------------------------------------------------------------------------------
    def end_of_day(self, day: date, sales: list[CanonicalSale]) -> EndOfDay:
        """Theoretical consumption (FR-STK-03), waste log and the weekly count (Sunday close)."""
        movements: list[Movement] = []
        usage: dict[str, Decimal] = defaultdict(Decimal)
        for sale in sales:
            for line in sale.lines:
                code = line.external_item_id.removeprefix("SIM-")
                for use in self.cat.recipes[code]:
                    usage[use.ingredient] += use.qty_base_per_portion * line.quantity
        close = self.at(day, self.site.closing)
        for ing, qty in sorted(usage.items()):
            if qty <= 0:
                continue
            self.state.on_hand[ing] = self.state.on_hand.get(ing, ZERO) - qty
            movements.append(Movement(ing, close + timedelta(minutes=50), day, "theoretical_consumption", -qty,
                                      self.state.wac.get(ing, ZERO), "sales_day", day.isoformat()))

        waste: list[WasteRecord] = []
        r = rng(self.org.slug, self.site.code, "waste", day)
        waste_at = close + timedelta(minutes=20)
        for ing in self.org.ingredients:
            item = self.cat.ingredients[ing]
            on_hand = self.state.on_hand.get(ing, ZERO)
            if on_hand <= 0:
                continue
            spoil = next((s for s in SPOILAGE if s.org == self.org.slug and s.site == self.site.code
                          and s.ingredient == ing and s.on == day), None)
            if spoil is not None:
                qty = on_hand
                reason, note = "spoilage", "End of shelf life - binned at close"
            elif item.shelf_life_days <= 7 and r.random() < 0.3:
                qty = (on_hand * Decimal(str(round(r.uniform(0.005, 0.025), 4)))).quantize(Decimal("0.1"))
                reason, note = r.choice(["spoilage", "prep", "over_production"]), None
            else:
                continue
            if qty <= 0:
                continue
            wac = self.state.wac.get(ing, ZERO)
            self.state.on_hand[ing] = on_hand - qty
            waste.append(WasteRecord(ing, waste_at, qty, reason, q2(qty * wac), note))
            movements.append(Movement(ing, waste_at, day, "waste", -qty, wac, "waste_day",
                                      f"{day.isoformat()}:{ing}"))

        count = None
        if day.weekday() == 6:
            counted_at = close + timedelta(minutes=40)
            lines = []
            for ing in self.org.ingredients:
                ledger = self.state.on_hand.get(ing, ZERO)
                noise = Decimal(str(round(r.gauss(0, 0.012), 4)))
                counted = max(ZERO, (ledger * (1 + noise)).quantize(Decimal("1")))
                lines.append((ing, counted, ledger))
                adjustment = counted - ledger
                if adjustment != 0:
                    self.state.on_hand[ing] = counted
                    movements.append(Movement(ing, counted_at, day, "count_adjustment", adjustment,
                                              self.state.wac.get(ing, ZERO), "stock_count", day.isoformat()))
            count = CountRecord(counted_at, lines)
        self.state.receipts_today = []
        return EndOfDay(movements, waste, count)

    # ---- purchasing ------------------------------------------------------------------------------
    def apply_par_changes(self, day: date) -> list[tuple[str, Decimal, Decimal, str]]:
        changes = []
        for change in PAR_CHANGES:
            if change.org == self.org.slug and change.site == self.site.code and change.on == day:
                old = self.state.par.get(change.ingredient, ZERO)
                self.state.par[change.ingredient] = change.par
                changes.append((change.ingredient, old, change.par, change.reason))
        return changes

    def next_delivery_after(self, supplier: str, day: date) -> date:
        spec = self.cat.suppliers[supplier]
        d = day + timedelta(days=1)
        while d.weekday() not in spec.delivery_weekdays:
            d += timedelta(days=1)
        return d

    def place_orders(self, day: date) -> list[POState]:
        """The kitchen's ordering after close: order-up-to expected need until the following delivery,
        plus a buffer and half a day of safety stock, at least the par level."""
        placed: list[POState] = []
        for spec in self.org.suppliers:
            delivery = day + timedelta(days=spec.lead_time_days)
            if delivery.weekday() not in spec.delivery_weekdays:
                continue
            following = self.next_delivery_after(spec.code, delivery)
            if any(po.supplier == spec.code and po.delivery_date == delivery for po in self.state.open_pos):
                continue
            projected = dict(self.state.on_hand)
            d = day + timedelta(days=1)
            while d < delivery:
                for ing, qty in self.expected_usage(d).items():
                    projected[ing] = projected.get(ing, ZERO) - qty
                d += timedelta(days=1)
            for po in self.state.open_pos:
                if po.delivery_date < delivery:
                    for line in po.lines:
                        projected[line.ingredient] = projected.get(line.ingredient, ZERO) + line.qty_base
            need: dict[str, Decimal] = defaultdict(Decimal)
            d = delivery
            while d < following:
                for ing, qty in self.expected_usage(d).items():
                    need[ing] += qty
                d += timedelta(days=1)
            safety_day = self.expected_usage(following)
            number = self.cat.po_number(self.site, spec.code, delivery)
            po_id = str(sid(self.org.slug, "po", number))
            lines: list[POLineState] = []
            for ing in self.org.ingredients:
                if self.state.suppliers.get(ing, self.cat.default_supplier[ing]) != spec.code:
                    continue
                target = need[ing] * ORDER_BUFFER + safety_day.get(ing, ZERO) * SAFETY_DAYS
                target = max(target, self.state.par.get(ing, ZERO))
                shortfall = target - max(ZERO, projected.get(ing, ZERO))
                product = self.cat.products[(spec.code, ing)]
                forced = next((s for s in SHORT_DELIVERIES if s.org == self.org.slug and s.site == self.site.code
                               and s.supplier == spec.code and s.ingredient == ing and s.on == delivery), None)
                if forced is not None:
                    units = forced.ordered
                elif shortfall <= 0:
                    continue
                else:
                    units = (shortfall / product.base_qty_per_unit).to_integral_value(rounding=ROUND_CEILING)
                lines.append(POLineState(
                    id=str(sid(self.org.slug, "po_line", number, ing)), ingredient=ing,
                    supplier_product_id=str(product.id), qty_units=units, qty_base=units * product.base_qty_per_unit,
                    unit_price_minor=self.cat.price_minor(spec.code, ing, day),
                ))
            if lines:
                po = POState(po_id, number, spec.code, day, delivery, lines)
                self.state.open_pos.append(po)
                placed.append(po)
        return placed

    # ---- opening balances (seed only) ------------------------------------------------------------
    def opening_stock(self, day: date) -> list[Movement]:
        """A week of expected usage at list price, booked before the first service."""
        usage: dict[str, Decimal] = defaultdict(Decimal)
        for n in range(7):
            for ing, qty in self.expected_usage(day + timedelta(days=n)).items():
                usage[ing] += qty
        out = []
        at = self.at(day, time(6, 0))
        for ing in self.org.ingredients:
            qty = max(usage[ing], self.state.par.get(ing, ZERO)).quantize(Decimal("1"))
            price = self.cat.price_per_base_minor(self.cat.default_supplier[ing], ing, day)
            self.state.on_hand[ing] = qty
            self.state.wac[ing] = price
            out.append(Movement(ing, at, day, "opening", qty, price, "opening", day.isoformat()))
        return out


def utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC)
