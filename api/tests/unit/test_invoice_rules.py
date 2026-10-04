"""Invoice rules: parsing, validation (FR-INV-06), normalisation (FR-INV-07), matching score (FR-INV-09),
price check (FR-INV-10), PO check (FR-INV-11), approval roles (FR-INV-15) and the state chart."""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.uom import UnknownConversion
from app.domain.purchasing.invoice_pipeline import sniff_mime
from app.domain.purchasing.invoice_rules import (
    TRANSITIONS,
    HeaderValues,
    LineValues,
    PriceCheckInput,
    can_transition,
    check_against_po,
    check_price,
    compute_totals,
    line_match_score,
    normalise_invoice_number,
    parse_date,
    parse_decimal,
    parse_vat_rate,
    qty_base_for,
    required_role,
    severity_for,
    validate,
)

TODAY = date(2026, 10, 2)


@pytest.mark.parametrize(("raw", "expected"), [
    ("1,234.50", "1234.50"), ("£94.80", "94.80"), ("₹50,000.00", "50000.00"), ("1.234,56", "1234.56"),
    ("12", "12"), ("(5.00)", "-5.00"), ("7,9", "7.9"), (None, None), ("", None), ("n/a", None),
])
def test_parse_decimal(raw, expected):
    assert parse_decimal(raw) == (Decimal(expected) if expected else None)


def test_parse_vat_and_dates():
    assert parse_vat_rate("20") == Decimal("0.2") and parse_vat_rate("20%") == Decimal("0.2")
    assert parse_vat_rate("0.2") == Decimal("0.2") and parse_vat_rate("0") == Decimal(0)
    assert parse_date("2026-10-02") == date(2026, 10, 2) == parse_date("02/10/2026")
    assert parse_date("Dec 12, 2024") == date(2024, 12, 12)
    assert parse_date("15/05/20231") is None  # the credit memo's typo is unreadable, not guessed
    assert normalise_invoice_number("INV-4471") == normalise_invoice_number("inv 4471") == "INV4471"


def test_sniff_mime_from_bytes():
    assert sniff_mime(b"%PDF-1.7 ...") == "application/pdf"
    assert sniff_mime(b"\xff\xd8\xff\xe0....") == "image/jpeg"
    assert sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert sniff_mime(b"\x00\x00\x00\x18ftypheic....") == "image/heic"
    assert sniff_mime(b"<html><script>") is None


def header(**kw):
    base = {"supplier_name": "Ashworth Meats Ltd", "supplier_known": True, "number": "INV-1", "invoice_date": TODAY,
            "currency": "GBP", "ai_subtotal_minor": None, "ai_vat_minor": None, "ai_total_minor": None}
    return HeaderValues(**{**base, **kw})


def line(n=1, qty="12", price="790", total=9480, vat="0"):
    return LineValues(n, "Chicken thigh", Decimal(qty), Decimal(price), total, Decimal(vat))


def test_clean_invoice_validates():
    issues, totals = validate(header(ai_subtotal_minor=9480, ai_vat_minor=0, ai_total_minor=9480), [line()], today=TODAY)
    assert issues == [] and totals.total_minor == 9480


def test_math_errors_line_and_totals():
    issues, _ = validate(header(ai_total_minor=9999), [line(total=9500)], today=TODAY)
    found = {(i.code, i.subject) for i in issues}
    assert ("math_error", "line:1") in found and ("math_error", "totals:total") in found
    assert all(i.blocks for i in issues if i.code == "math_error")


def test_vat_reconciles_per_rate():
    lines = [line(1, "2", "2500000", 5_000_000, "0.18"), line(2, "2", "50000", 100_000, "0.18"),
             line(3, "1", "500000", 500_000, "0")]
    totals = compute_totals(lines)
    assert totals.vat_minor == 918_000 and totals.total_minor == 6_518_000
    issues, _ = validate(header(currency="INR", ai_vat_minor=918_000, ai_total_minor=6_518_000), lines, today=TODAY)
    assert issues == []


def test_dates_and_required_fields():
    issues, _ = validate(header(number=None, invoice_date=date(2026, 10, 9), currency="XYZ"), [], today=TODAY)
    messages = " ".join(i.message for i in issues)
    assert {i.code for i in issues} == {"missing_field"}
    assert "invoice number" in messages and "in the future" in messages and "ISO 4217" in messages
    issues, _ = validate(header(invoice_date=date(2024, 12, 12)), [line()], today=TODAY)
    assert "more than 18 months old" in issues[0].message


@given(st.lists(st.tuples(st.integers(1, 50), st.integers(1, 100_000), st.sampled_from(["0", "0.05", "0.2"])),
                min_size=1, max_size=12))
def test_totals_are_sum_of_lines(rows):
    lines = [line(n, str(q), str(p), q * p, v) for n, (q, p, v) in enumerate(rows, start=1)]
    totals = compute_totals(lines)
    assert totals.subtotal_minor == sum(q * p for q, p, _ in rows)
    assert totals.total_minor == totals.subtotal_minor + totals.vat_minor == totals.subtotal_minor + sum(
        totals.vat_by_rate.values())


@pytest.mark.parametrize(("qty", "uom", "pack", "expected"), [
    ("12", "kg", "5kg case", "12000"),       # invoiced in the purchase unit
    ("1", "case", "60 x 67g", "60"),         # case of 60 sausages, stocked each
    ("2", "kg", "2.27kg pack", "2000"),
    ("3", "case", "2 x 5kg", "30000"),        # different pack unit -> pack expression
])
def test_qty_base_normalisation(qty, uom, pack, expected):
    base_unit = "each" if "x 67g" in (pack or "") else "g"
    purchase, bq = ("case", Decimal(60)) if base_unit == "each" else ("kg", Decimal(1000))
    if expected == "30000":
        purchase, bq = "bag", Decimal(1000)
    assert qty_base_for(Decimal(qty), uom, pack, base_unit=base_unit, purchase_unit=purchase, base_qty_per_unit=bq,
                        conversions={}) == Decimal(expected)


def test_unknown_unit_conversion():
    with pytest.raises(UnknownConversion):
        qty_base_for(Decimal(1), "tub", None, base_unit="g", purchase_unit="kg", base_qty_per_unit=Decimal(1000),
                     conversions={})


def test_line_match_score_weights():
    assert line_match_score(1.0, True, 1.0) == 1.0
    assert line_match_score(0.9, True, 0.5) == pytest.approx(0.84)  # just below auto-match
    assert line_match_score(0.5, False, 0.5) == pytest.approx(0.4)  # unmatched


def test_price_increase_s1():
    history = [(date(2026, 9, d), Decimal("0.67")) for d in range(1, 31)]
    issues = check_price(PriceCheckInput(Decimal("0.79"), Decimal(12000), "g", history), pct=0.05,
                         min_abs_per_unit_minor=5, robust_z=3, warning_minor=2500, critical_minor=15000, as_of=TODAY)
    (inc,) = issues
    assert inc.code == "price_increase" and inc.severity == "info"
    assert inc.facts["change_pct"] == 17.9 and inc.facts["impact_minor"] == 1440 and inc.facts["robust_z"] is None


def test_small_moves_and_contract_breach():
    history = [(date(2026, 9, 1), Decimal("0.67"))]
    assert check_price(PriceCheckInput(Decimal("0.68"), Decimal(1000), "g", history), pct=0.05, min_abs_per_unit_minor=5,
                       robust_z=3, warning_minor=2500, critical_minor=15000, as_of=TODAY) == []
    issues = check_price(PriceCheckInput(Decimal("0.70"), Decimal(10000), "g", [], Decimal("0.67")), pct=0.05,
                         min_abs_per_unit_minor=5, robust_z=3, warning_minor=2500, critical_minor=15000, as_of=TODAY)
    assert [i.code for i in issues] == ["contract_breach"]


def test_robust_z_flags_outliers():
    history = [(date(2026, 9, d), Decimal("1.00") + Decimal(d % 3) / 100) for d in range(1, 29)]
    issues = check_price(PriceCheckInput(Decimal("1.06"), Decimal(100), "each", history), pct=0.5,
                         min_abs_per_unit_minor=5, robust_z=3, warning_minor=2500, critical_minor=15000, as_of=TODAY)
    assert issues and issues[0].facts["robust_z"] >= 3


def test_po_check_s2():
    issues = check_against_po(line_no=1, description="Chicken thigh", invoiced_base=Decimal(12000),
                              invoiced_price_per_base=Decimal("0.79"), ordered_base=Decimal(20000),
                              received_base=Decimal(12000), po_price_per_base=Decimal("0.67"),
                              unit_size_base=Decimal(1000), base_unit="g", po_number="PO-CP1-261002-ASH",
                              qty_tolerance=0.02, price_tolerance=0.01)
    assert sorted(i.code for i in issues) == ["price_mismatch", "qty_mismatch"]
    qty = next(i for i in issues if i.code == "qty_mismatch")
    assert qty.facts["difference_pct"] == -40.0 and "12 kg invoiced vs 20 kg ordered" in qty.message


def test_po_check_tolerances():
    common = {"line_no": 1, "description": "x", "invoiced_price_per_base": Decimal(1), "received_base": None,
              "po_price_per_base": Decimal(1), "unit_size_base": Decimal(1000), "base_unit": "g", "po_number": "P",
              "qty_tolerance": 0.02, "price_tolerance": 0.01}
    assert check_against_po(invoiced_base=Decimal(100_000), ordered_base=Decimal(101_000), **common) == []
    assert check_against_po(invoiced_base=Decimal(3000), ordered_base=Decimal(4000), **common)


def test_severity_bands():
    assert [severity_for(v, 2500, 15000) for v in (2499, 2500, 14999, 15000)] == ["info", "warning", "warning", "critical"]


def test_required_role():
    limits = {"head_chef": 50_000, "general_manager": 500_000, "owner": None}
    assert required_role(total_minor=40_000, limits=limits, exceptions=[]) == "head_chef"
    assert required_role(total_minor=60_000, limits=limits, exceptions=[]) == "general_manager"
    assert required_role(total_minor=600_000, limits=limits, exceptions=[]) == "owner"
    assert required_role(total_minor=1_000, limits=limits,
                         exceptions=[("price_increase", "accepted", "")]) == "general_manager"
    assert required_role(total_minor=1_000, limits=limits,
                         exceptions=[("qty_mismatch", "open", "general_manager")]) == "general_manager"


def test_state_chart():
    assert can_transition("received", "classifying") and not can_transition("received", "approved")
    assert can_transition("approved", "ready_for_approval")  # an edit voids the approval
    assert all(not TRANSITIONS[s] for s in ("posted", "rejected", "not_invoice", "duplicate"))


def test_unchanged_price_is_not_an_increase_even_above_the_median():
    history = [(date(2026, 7, 1), Decimal("0.80")), (date(2026, 8, 1), Decimal("0.82")), (date(2026, 9, 1), Decimal("0.84"))]
    issues = check_price(PriceCheckInput(Decimal("0.84"), Decimal(5000), "g", history), pct=0.05, min_abs_per_unit_minor=5,
                         robust_z=3, warning_minor=2500, critical_minor=15000, as_of=TODAY)
    assert issues == []
