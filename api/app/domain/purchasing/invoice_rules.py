"""Pure invoice rules (no I/O): parsing, deterministic validation (FR-INV-06), unit normalisation
(FR-INV-07), match scoring (FR-INV-09), price checks (FR-INV-10), PO/receipt checks (FR-INV-11),
duplicate rules (FR-INV-12), the exception policy (Table 17) and the intake state chart (FR-INV-13)."""

import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.core.money import CURRENCY_EXPONENT, is_iso_currency
from app.core.uom import UnknownConversion, factor_to_base, normalise_unit, parse_pack

# ---------------------------------------------------------------------------------------------------
# State chart (Figure 7)
# ---------------------------------------------------------------------------------------------------
TRANSITIONS: dict[str, set[str]] = {
    "received": {"classifying", "failed", "duplicate"},
    "classifying": {"extracting", "not_invoice", "needs_review", "failed"},
    "extracting": {"validating", "failed"},
    "validating": {"matching", "needs_review", "failed"},
    "matching": {"needs_review", "ready_for_approval", "failed"},
    "needs_review": {"needs_review", "ready_for_approval", "extracting", "rejected"},
    "ready_for_approval": {"ready_for_approval", "needs_review", "approved", "rejected"},
    "approved": {"posted", "ready_for_approval", "needs_review", "rejected"},
    "failed": {"received"},
    "posted": set(),
    "rejected": set(),
    "not_invoice": set(),
    "duplicate": set(),
}
TERMINAL = {"posted", "rejected", "not_invoice", "duplicate"}
EDITABLE = {"needs_review", "ready_for_approval", "approved"}


def can_transition(src: str, dst: str) -> bool:
    return dst in TRANSITIONS.get(src, set())


# ---------------------------------------------------------------------------------------------------
# Exception policy (Table 17)
# ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ExceptionPolicy:
    blocks: bool  # blocks approval while open
    acceptable: bool  # may be accepted with a note (otherwise it must be corrected)
    requires_role: str | None = None  # approval needs at least this role while present


POLICY: dict[str, ExceptionPolicy] = {
    "math_error": ExceptionPolicy(True, False),
    "missing_field": ExceptionPolicy(True, False),
    "unmatched_unit": ExceptionPolicy(True, False),
    "unknown_supplier": ExceptionPolicy(True, False),
    "unmatched_line": ExceptionPolicy(True, False),
    "price_increase": ExceptionPolicy(False, True),  # blocks only when critical (needs an acceptance note)
    "contract_breach": ExceptionPolicy(False, True, "general_manager"),
    "qty_mismatch": ExceptionPolicy(False, True, "general_manager"),
    "price_mismatch": ExceptionPolicy(False, True, "general_manager"),
    "possible_duplicate": ExceptionPolicy(True, True),
    "low_confidence": ExceptionPolicy(True, True),
}


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    facts: dict[str, Any] = field(default_factory=dict)
    line_no: int | None = None
    subject: str = ""  # makes the fingerprint unique per line/field/duplicate

    @property
    def fingerprint(self) -> str:
        return f"{self.code}:{self.subject or (f'line:{self.line_no}' if self.line_no is not None else 'invoice')}"

    @property
    def blocks(self) -> bool:
        policy = POLICY[self.code]
        return policy.blocks or (self.code == "price_increase" and self.severity == "critical")


def severity_for(impact_minor: int, warning_minor: int, critical_minor: int) -> str:
    """info under 25, warning under 150, critical at 150 or more (configurable)."""
    amount = abs(impact_minor)
    if amount >= critical_minor:
        return "critical"
    if amount >= warning_minor:
        return "warning"
    return "info"


# ---------------------------------------------------------------------------------------------------
# Parsing extracted strings (the AI copies numbers as printed)
# ---------------------------------------------------------------------------------------------------
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    negative = (text.startswith("(") and text.endswith(")")) or text.startswith("-") or text.endswith("-")
    cleaned = re.sub(r"[^\d.,]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):  # 1.234,56 (continental)
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:  # 1,234.56
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        head, _, tail = cleaned.rpartition(",")
        cleaned = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else cleaned.replace(",", "")
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -number if negative else number


def parse_vat_rate(value: Any) -> Decimal | None:
    """'20', '20%', '0.2' -> 0.20 (fraction)."""
    number = parse_decimal(value)
    if number is None:
        return None
    return (number / 100 if number > 1 else number).quantize(Decimal("0.0001"))


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y",
                 "%B %d, %Y", "%d/%m/%y")


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def to_minor(amount: Decimal | None, currency: str) -> int | None:
    if amount is None:
        return None
    exp = CURRENCY_EXPONENT.get(currency, 2)
    return int((amount * (10**exp)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def unit_price_minor(amount: Decimal | None, currency: str) -> Decimal | None:
    if amount is None:
        return None
    return (amount * (10 ** CURRENCY_EXPONENT.get(currency, 2))).quantize(Decimal("0.0001"))


def normalise_text(text: str | None) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return " ".join(t.split())


def normalise_invoice_number(number: str | None) -> str | None:
    if not number:
        return None
    cleaned = re.sub(r"[^A-Z0-9]", "", number.upper())
    return cleaned or None


def normalise_vat_number(vat: str | None) -> str | None:
    if not vat:
        return None
    cleaned = re.sub(r"[^A-Z0-9]", "", vat.upper())
    return cleaned or None


def normalise_supplier_name(name: str | None) -> str:
    text = normalise_text(name)
    text = re.sub(r"\b(ltd|limited|plc|llp|co|the|and|inc|llc|gmbh)\b", " ", text)
    return " ".join(text.split())


# ---------------------------------------------------------------------------------------------------
# Deterministic validation (FR-INV-06)
# ---------------------------------------------------------------------------------------------------
@dataclass
class LineValues:
    line_no: int
    description: str
    quantity: Decimal | None
    unit_price_minor: Decimal | None
    line_total_minor: int | None
    vat_rate: Decimal | None
    non_stock: bool = False


@dataclass
class HeaderValues:
    supplier_name: str | None
    supplier_known: bool
    number: str | None
    invoice_date: date | None
    currency: str | None
    ai_subtotal_minor: int | None
    ai_vat_minor: int | None
    ai_total_minor: int | None


@dataclass
class Totals:
    subtotal_minor: int
    vat_minor: int
    total_minor: int
    vat_by_rate: dict[str, int]


def compute_totals(lines: list[LineValues]) -> Totals:
    """Totals used by the system are recomputed from lines; VAT is rounded once per rate."""
    by_rate: dict[Decimal, int] = {}
    for line in lines:
        if line.line_total_minor is None:
            continue
        rate = line.vat_rate or Decimal(0)
        by_rate[rate] = by_rate.get(rate, 0) + line.line_total_minor
    vat = {str(rate): int((Decimal(base) * rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
           for rate, base in by_rate.items()}
    subtotal = sum(by_rate.values())
    vat_total = sum(vat.values())
    return Totals(subtotal, vat_total, subtotal + vat_total, vat)


def validate(header: HeaderValues, lines: list[LineValues], *, today: date, max_future_days: int = 2,
             max_age_months: int = 18) -> tuple[list[Issue], Totals]:
    issues: list[Issue] = []

    def missing(field_name: str, message: str, **facts: Any) -> None:
        issues.append(Issue("missing_field", "warning", message, {"field": field_name, **facts}, subject=field_name))

    if not header.supplier_name and not header.supplier_known:
        missing("supplier", "The supplier name is missing.")
    if not header.number:
        missing("invoice_number", "The invoice number is missing.")
    if header.invoice_date is None:
        missing("invoice_date", "The invoice date is missing or unreadable.")
    else:
        if header.invoice_date > today + timedelta(days=max_future_days):
            missing("invoice_date", f"The invoice date {header.invoice_date.isoformat()} is more than "
                    f"{max_future_days} days in the future.", invoice_date=header.invoice_date.isoformat(),
                    today=today.isoformat())
        oldest = today - timedelta(days=round(max_age_months * 30.44))
        if header.invoice_date < oldest:
            missing("invoice_date", f"The invoice date {header.invoice_date.isoformat()} is more than "
                    f"{max_age_months} months old.", invoice_date=header.invoice_date.isoformat(),
                    oldest_allowed=oldest.isoformat())
    if not header.currency or not is_iso_currency(header.currency):
        missing("currency", f"The currency {header.currency!r} is not a supported ISO 4217 code.",
                currency=header.currency)
    if not lines:
        missing("lines", "No invoice lines were found.")

    for line in lines:
        subject = f"line:{line.line_no}"
        if line.quantity is None or line.line_total_minor is None or line.unit_price_minor is None:
            absent = [n for n, v in (("quantity", line.quantity), ("unit_price", line.unit_price_minor),
                                     ("line_total", line.line_total_minor)) if v is None]
            issues.append(Issue("missing_field", "warning", f"Line {line.line_no} is missing {', '.join(absent)}.",
                                {"fields": absent}, line_no=line.line_no, subject=f"{subject}:fields"))
            continue
        if line.quantity <= 0 and not line.non_stock:
            issues.append(Issue("missing_field", "warning", f"Line {line.line_no} quantity must be positive.",
                                {"quantity": str(line.quantity)}, line_no=line.line_no, subject=f"{subject}:qty"))
        expected = line.quantity * line.unit_price_minor
        if abs(expected - line.line_total_minor) > 1:
            issues.append(Issue(
                "math_error", "critical",
                f"Line {line.line_no}: {line.quantity} x {line.unit_price_minor / 100:.2f} = "
                f"{expected / 100:.2f}, but the line total is {line.line_total_minor / 100:.2f}.",
                {"quantity": str(line.quantity), "unit_price_minor": str(line.unit_price_minor),
                 "expected_minor": int(expected.to_integral_value(rounding=ROUND_HALF_UP)),
                 "line_total_minor": line.line_total_minor}, line_no=line.line_no, subject=subject))

    totals = compute_totals(lines)
    tolerance = max(1, len(lines))
    for name, ours, theirs in (("subtotal", totals.subtotal_minor, header.ai_subtotal_minor),
                               ("vat", totals.vat_minor, header.ai_vat_minor),
                               ("total", totals.total_minor, header.ai_total_minor)):
        if theirs is not None and abs(ours - theirs) > tolerance:
            issues.append(Issue("math_error", "critical",
                                f"The printed {name} {theirs / 100:.2f} does not reconcile with the lines "
                                f"({ours / 100:.2f}).",
                                {"field": name, "computed_minor": ours, "printed_minor": theirs,
                                 "difference_minor": ours - theirs, "vat_by_rate": totals.vat_by_rate},
                                subject=f"totals:{name}"))
    return issues, totals


# ---------------------------------------------------------------------------------------------------
# Unit normalisation (FR-INV-07)
# ---------------------------------------------------------------------------------------------------
def qty_base_for(quantity: Decimal, uom: str | None, pack_size: str | None, *, base_unit: str, purchase_unit: str,
                 base_qty_per_unit: Decimal, conversions: dict[str, Decimal]) -> Decimal:
    """Invoiced quantity in the ingredient's base unit. Raises UnknownConversion (-> unmatched_unit)."""
    unit = normalise_unit(uom)
    purchase = normalise_unit(purchase_unit)
    extra = {**conversions, purchase or purchase_unit: base_qty_per_unit}
    if unit is None or unit == purchase:
        return quantity * base_qty_per_unit
    pack = parse_pack(pack_size)
    if pack is not None and pack.unit is not None and unit in ("case", "pack", "box", "tray", "bag", "each"):
        return quantity * pack.total * factor_to_base(pack.unit, base_unit, extra)
    return quantity * factor_to_base(unit, base_unit, extra)


def is_unit_compatible(uom: str | None, *, base_unit: str, purchase_unit: str, base_qty_per_unit: Decimal,
                       conversions: dict[str, Decimal], pack_size: str | None = None) -> bool:
    try:
        qty_base_for(Decimal(1), uom, pack_size, base_unit=base_unit, purchase_unit=purchase_unit,
                     base_qty_per_unit=base_qty_per_unit, conversions=conversions)
        return True
    except UnknownConversion:
        return False


# ---------------------------------------------------------------------------------------------------
# Matching (FR-INV-08/09)
# ---------------------------------------------------------------------------------------------------
def line_match_score(text_similarity: float, unit_compatible: bool, price_proximity: float) -> float:
    """0.6 text similarity + 0.2 unit compatibility + 0.2 price proximity to the last price."""
    return round(0.6 * text_similarity + 0.2 * (1.0 if unit_compatible else 0.0) + 0.2 * price_proximity, 4)


def price_proximity(price_per_base: Decimal | None, last_price_per_base: Decimal | None) -> float:
    if price_per_base is None or not last_price_per_base:
        return 0.5  # no history: neutral
    return max(0.0, 1.0 - float(abs(price_per_base - last_price_per_base) / last_price_per_base))


# ---------------------------------------------------------------------------------------------------
# Price check (FR-INV-10)
# ---------------------------------------------------------------------------------------------------
def display_factor(base_unit: str) -> int:
    """Prices are shown per kg / l / each: 1000 base units for g and ml."""
    return 1000 if base_unit in ("g", "ml") else 1


def display_unit(base_unit: str) -> str:
    return {"g": "kg", "ml": "l"}.get(base_unit, "each")


@dataclass(frozen=True)
class PriceCheckInput:
    price_per_base: Decimal  # minor units per base unit
    qty_base: Decimal
    base_unit: str
    history: list[tuple[date, Decimal]]  # (observed_on, price_per_base) before this invoice, oldest first
    contract_price_per_base: Decimal | None = None


def check_price(p: PriceCheckInput, *, pct: float, min_abs_per_unit_minor: int, robust_z: float,
                warning_minor: int, critical_minor: int, as_of: date) -> list[Issue]:
    issues: list[Issue] = []
    factor = display_factor(p.base_unit)
    unit = display_unit(p.base_unit)
    price_disp = p.price_per_base * factor
    if p.contract_price_per_base is not None and p.price_per_base > p.contract_price_per_base * Decimal("1.0001"):
        impact = int(((p.price_per_base - p.contract_price_per_base) * p.qty_base).to_integral_value(ROUND_HALF_UP))
        issues.append(Issue("contract_breach", "critical",
                            f"Price {price_disp / 100:.2f}/{unit} is above the agreed contract price "
                            f"{p.contract_price_per_base * factor / 100:.2f}/{unit}.",
                            {"price_per_unit_minor": _r(price_disp), "contract_per_unit_minor":
                             _r(p.contract_price_per_base * factor), "impact_minor": impact, "unit": unit}))
    if not p.history:
        return issues
    last = p.history[-1][1]
    window = [v for d, v in p.history if d >= as_of - timedelta(days=90)] or [last]
    median = Decimal(str(statistics.median(window)))
    mad = Decimal(str(statistics.median([abs(v - median) for v in window])))
    z = float((p.price_per_base - median) / (Decimal("1.4826") * mad)) if mad > 0 else None
    change = (p.price_per_base - last) / last if last else Decimal(0)
    abs_increase_disp = (p.price_per_base - last) * factor
    rule_pct = change >= Decimal(str(pct)) and abs_increase_disp >= min_abs_per_unit_minor
    # The robust z-score catches outliers against the 90-day median, but only for an actual increase on
    # this invoice: a price equal to the last one is not news even if it drifted above the median.
    rule_z = z is not None and z >= robust_z and p.price_per_base > last
    if rule_pct or rule_z:
        impact = int(((p.price_per_base - last) * p.qty_base).to_integral_value(ROUND_HALF_UP))
        issues.append(Issue(
            "price_increase", severity_for(impact, warning_minor, critical_minor),
            f"Price {price_disp / 100:.2f}/{unit} is {change * 100:+.1f}% vs the last price "
            f"{last * factor / 100:.2f}/{unit} (90-day median {median * factor / 100:.2f}/{unit}); "
            f"{impact / 100:.2f} more on this invoice.",
            {"price_per_unit_minor": _r(price_disp), "last_per_unit_minor": _r(last * factor),
             "median_90d_per_unit_minor": _r(median * factor), "change_pct": round(float(change) * 100, 1),
             "robust_z": round(z, 2) if z is not None else None, "impact_minor": impact, "unit": unit,
             "last_observed_on": p.history[-1][0].isoformat()}))
    return issues


def _r(value: Decimal) -> int:
    return int(value.to_integral_value(ROUND_HALF_UP))


# ---------------------------------------------------------------------------------------------------
# PO and goods-received check (FR-INV-11)
# ---------------------------------------------------------------------------------------------------
def qty_differs(invoiced: Decimal, reference: Decimal, unit_size: Decimal, tolerance_pct: float) -> bool:
    """More than 2% (configurable) or more than one purchase unit apart."""
    diff = abs(invoiced - reference)
    if reference == 0:
        return diff > 0
    return diff / reference > Decimal(str(tolerance_pct)) or diff > unit_size


def check_against_po(*, line_no: int, description: str, invoiced_base: Decimal, invoiced_price_per_base: Decimal,
                     ordered_base: Decimal | None, received_base: Decimal | None, po_price_per_base: Decimal | None,
                     unit_size_base: Decimal, base_unit: str, po_number: str | None, qty_tolerance: float,
                     price_tolerance: float) -> list[Issue]:
    issues: list[Issue] = []
    factor = display_factor(base_unit)
    unit = display_unit(base_unit)

    def fmt(q: Decimal) -> str:
        return f"{(q / factor).normalize():f} {unit}"

    for ref_name, ref in (("ordered", ordered_base), ("received", received_base)):
        if ref is not None and qty_differs(invoiced_base, ref, unit_size_base, qty_tolerance):
            pct = (invoiced_base - ref) / ref * 100 if ref else Decimal(100)
            issues.append(Issue(
                "qty_mismatch", "warning",
                f"Line {line_no} ({description}): {fmt(invoiced_base)} invoiced vs {fmt(ref)} {ref_name}"
                + (f" on {po_number}" if ref_name == "ordered" and po_number else "") + f" ({pct:+.0f}%).",
                {"invoiced_base": str(invoiced_base), f"{ref_name}_base": str(ref), "difference_pct": round(float(pct), 1),
                 "unit": unit, "po_number": po_number, "against": ref_name},
                line_no=line_no, subject=f"line:{line_no}:{ref_name}"))
    if po_price_per_base and abs(invoiced_price_per_base - po_price_per_base) / po_price_per_base > Decimal(str(price_tolerance)):
        pct = (invoiced_price_per_base - po_price_per_base) / po_price_per_base * 100
        issues.append(Issue(
            "price_mismatch", "warning",
            f"Line {line_no} ({description}): {invoiced_price_per_base * factor / 100:.2f}/{unit} invoiced vs "
            f"{po_price_per_base * factor / 100:.2f}/{unit} on {po_number or 'the PO'} ({pct:+.1f}%).",
            {"invoiced_per_unit_minor": _r(invoiced_price_per_base * factor),
             "po_per_unit_minor": _r(po_price_per_base * factor), "difference_pct": round(float(pct), 1),
             "unit": unit, "po_number": po_number}, line_no=line_no, subject=f"line:{line_no}"))
    return issues


# ---------------------------------------------------------------------------------------------------
# Approval rules (FR-INV-15)
# ---------------------------------------------------------------------------------------------------
ROLE_RANK = {"shift_manager": 1, "head_chef": 2, "general_manager": 3, "owner": 4}


def required_role(*, total_minor: int, limits: dict[str, int | None], exceptions: list[tuple[str, str, str]]) -> str:
    """Minimum role allowed to approve. `exceptions` = (code, status, requires_role or '').

    Clean invoices under the Head Chef limit: Head Chef. Accepted exceptions, GM-only exceptions or a
    total above the Head Chef limit: General Manager (or Owner above the GM limit)."""
    needed = "head_chef"
    if any(status == "accepted" or req == "general_manager" for _, status, req in exceptions):
        needed = "general_manager"
    for role in ("head_chef", "general_manager", "owner"):
        if ROLE_RANK[role] < ROLE_RANK[needed]:
            continue
        limit = limits.get(role)
        if limit is None or total_minor <= limit:
            return role
    return "owner"


def within_limit(role: str, total_minor: int, limits: dict[str, int | None]) -> bool:
    limit = limits.get(role)
    return limit is None or total_minor <= limit
