"""PosPort adapter over a POS CSV export (FR-ING-04; the upload/validation workflow is FR-ING-03).

Expected columns: order_id, business_date, opened_at, closed_at, covers, channel, item_code, item_name,
quantity, unit_price, vat_rate, discount, void_quantity. One row per order line; prices in major units.
Shift and cash-up exports are optional companions with their own columns.
"""

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.core.money import Money
from app.ports.errors import PermanentError
from app.ports.pos import CanonicalCashUp, CanonicalSale, CanonicalSaleLine, CanonicalShift

PROVIDER = "csv"
REQUIRED = ("order_id", "business_date", "opened_at", "closed_at", "item_code", "item_name", "quantity",
            "unit_price", "vat_rate")


@dataclass(frozen=True)
class RowError:
    row: int
    field: str
    message: str


def parse_sales_csv(text: str, currency: str) -> tuple[list[CanonicalSale], list[RowError]]:
    """Row-level validation: valid orders are returned, every problem is reported with its row number."""
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise PermanentError(f"CSV is missing columns: {', '.join(missing)}", provider=PROVIDER)
    orders: dict[str, dict] = {}
    lines: dict[str, list[CanonicalSaleLine]] = defaultdict(list)
    errors: list[RowError] = []
    bad_orders: set[str] = set()
    for n, row in enumerate(reader, start=2):
        oid = (row.get("order_id") or "").strip()
        try:
            if not oid:
                raise ValueError("order_id is empty")
            day = date.fromisoformat(row["business_date"].strip())
            opened = datetime.fromisoformat(row["opened_at"].strip())
            closed = datetime.fromisoformat(row["closed_at"].strip())
            if opened.tzinfo is None or closed.tzinfo is None:
                raise ValueError("timestamps must include a UTC offset")
            qty = Decimal(row["quantity"])
            if qty < 0:
                raise ValueError("quantity must not be negative")
            line = CanonicalSaleLine(
                external_item_id=row["item_code"].strip(), name=row["item_name"].strip(), quantity=qty,
                unit_price_minor=Money.from_decimal(row["unit_price"], currency).minor,
                vat_rate=Decimal(row["vat_rate"]) / (100 if Decimal(row["vat_rate"]) > 1 else 1),
                discount_minor=Money.from_decimal(row.get("discount") or "0", currency).minor,
                void_quantity=Decimal(row.get("void_quantity") or 0),
            )
        except (ValueError, KeyError, InvalidOperation) as exc:
            errors.append(RowError(n, "row", str(exc)))
            if oid:
                bad_orders.add(oid)
            continue
        orders.setdefault(oid, {"day": day, "opened": opened, "closed": closed,
                                "covers": int(row.get("covers") or 1), "channel": row.get("channel") or "dine_in"})
        lines[oid].append(line)
    sales = [CanonicalSale(oid, o["day"], o["opened"], o["closed"], o["covers"], o["channel"], currency,
                           tuple(lines[oid])) for oid, o in orders.items() if oid not in bad_orders]
    return sales, errors


def error_report(errors: list[RowError]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["row", "field", "message"])
    writer.writerows([(e.row, e.field, e.message) for e in errors])
    return buf.getvalue()


class CsvPos:
    provider = PROVIDER

    def __init__(self, sales_csv: str, currency: str, *, shifts: list[CanonicalShift] | None = None,
                 cash_ups: list[CanonicalCashUp] | None = None) -> None:
        self.sales, self.errors = parse_sales_csv(sales_csv, currency)
        self.shifts = shifts or []
        self.cash_ups = cash_ups or []

    async def fetch_sales(self, day: date) -> list[CanonicalSale]:
        return [s for s in self.sales if s.business_date == day]

    async def fetch_shifts(self, day: date) -> list[CanonicalShift]:
        return [s for s in self.shifts if s.business_date == day]

    async def fetch_cash_ups(self, day: date) -> list[CanonicalCashUp]:
        return [c for c in self.cash_ups if c.business_date == day]
