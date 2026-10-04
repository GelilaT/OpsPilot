"""Simulator, scenarios and documents: determinism and the SRS worked-example arithmetic (Appendix B)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.seed.users import better_auth_hash, verify_better_auth_hash
from app.simulation.catalogue import Catalogue
from app.simulation.invoice_render import DocLine, InvoiceDoc, Party, render_pdf
from app.simulation.pantry import PANTRY
from app.simulation.profiles import COPPER_POT, NORTHSIDE, PROFILES
from app.simulation.scenarios import SEED_END
from app.simulation.world import SiteWorld, WorldState

# Produced by better-auth's own hashPassword() (node, @better-auth/utils 1.7) for the password below.
NODE_VECTOR = ("28fc3d418ac11978f8bd0dc8615a768c:3ed22ad0c784240436b0d53fc0f6e60335ac4978dffa637a65fdfbff05af12df3edbee"
               "5e1fc14cb9a8812443dd977542e331bef1c383c88f3ea468b22bcbc09f")


def test_better_auth_password_hash_is_compatible():
    assert verify_better_auth_hash(NODE_VECTOR, "correct horse battery staple")
    assert not verify_better_auth_hash(NODE_VECTOR, "wrong password")
    ours = better_auth_hash("another-password-1")
    assert verify_better_auth_hash(ours, "another-password-1")


@pytest.mark.parametrize("profile", list(PROFILES.values()), ids=list(PROFILES))
def test_profiles_match_appendix_c(profile):
    used = {line.ingredient for item in profile.menu for line in item.recipe}
    assert len(profile.menu) == 42
    assert len(profile.ingredients) == 65 and len(set(profile.ingredients)) == 65
    assert used == set(profile.ingredients)
    assert len(profile.suppliers) == 6
    cat = Catalogue(profile)
    assert set(cat.default_supplier) == set(profile.ingredients)  # every ingredient has a default supplier
    overlaps = [s for s in profile.suppliers if s.alternatives]
    assert len(overlaps) >= 2  # two suppliers overlap on proteins and dry goods


def _cost(cat: Catalogue, code: str, day: date) -> Decimal:
    total = Decimal(0)
    for use in cat.recipes[code]:
        total += use.qty_base_per_portion * cat.price_per_base_minor(cat.default_supplier[use.ingredient], use.ingredient,
                                                                       day)
    return total / 100


def test_chicken_wrap_worked_example():
    """Appendix B: cost 2.53 -> 2.83, chicken explains 80%, GP 68.1% -> 64.3%; price review to 9.95 -> 65.9%."""
    cat = Catalogue(COPPER_POT)
    before, after = _cost(cat, "chicken_wrap", date(2026, 9, 4)), _cost(cat, "chicken_wrap", date(2026, 10, 2))
    price_ex_vat = Decimal("9.50") / Decimal("1.2")
    assert round(before, 2) == Decimal("2.53") and round(after, 2) == Decimal("2.83")
    assert round((price_ex_vat - before) / price_ex_vat * 100, 1) == Decimal("68.1")
    assert round((price_ex_vat - after) / price_ex_vat * 100, 1) == Decimal("64.3")
    chicken = Decimal("0.200") * (Decimal("7.90") - Decimal("6.70"))
    assert round(chicken / (after - before) * 100) == 80
    assert round((Decimal("9.95") / Decimal("1.2") - after) / (Decimal("9.95") / Decimal("1.2")) * 100, 1) == Decimal("65.9")


def test_s1_price_event_and_s3_alternative():
    cat = Catalogue(COPPER_POT)
    assert cat.price_minor("ASH", "chicken_thigh", date(2026, 10, 1)) == 670
    assert cat.price_minor("ASH", "chicken_thigh", date(2026, 10, 2)) == 790  # +18%
    assert cat.price_minor("BRM", "chicken_thigh", date(2026, 10, 2)) == 719
    # S3 supplier switch saving per kg (0.71) - weekly saving is computed from actual usage
    assert 790 - 719 == 71


def test_invoice_number_anchor_and_po_numbers():
    cat = Catalogue(COPPER_POT)
    site = COPPER_POT.sites[0]
    assert cat.invoice_number(site, "ASH", date(2026, 10, 2)) == "INV-4471"
    assert cat.invoice_number(site, "ASH", date(2026, 10, 1)) == "INV-4470"
    assert cat.po_number(site, "ASH", date(2026, 10, 2)) == "PO-CP1-261002-ASH"


def _run(profile, days: int):
    cat = Catalogue(profile)
    site = profile.sites[0]
    world = SiteWorld(profile, site, cat, WorldState({}, {}, par=dict(profile.par_levels)))
    start = SEED_END - timedelta(days=days - 1)
    world.opening_stock(start)
    out = []
    day = start
    while day <= SEED_END:
        world.apply_par_changes(day)
        world.deliveries(day)
        sales, _ = world.sales(day)
        world.end_of_day(day, sales)
        world.place_orders(day)
        out.append((day, len(sales), sum(len(s.lines) for s in sales)))
        day += timedelta(days=1)
    return out, world


def test_simulator_is_deterministic():
    a, _ = _run(NORTHSIDE, 10)
    b, _ = _run(NORTHSIDE, 10)
    assert a == b


def test_s2_preconditions_hold_after_history():
    _, world = _run(COPPER_POT, 21)
    assert world.state.on_hand["chicken_thigh"] == 0  # binned at close on Thursday 1 Oct
    po = next(p for p in world.state.open_pos if p.supplier == "ASH" and p.delivery_date == date(2026, 10, 2))
    chicken = next(line for line in po.lines if line.ingredient == "chicken_thigh")
    assert chicken.qty_units == 20 and chicken.unit_price_minor == 670
    deliveries = world.deliveries(date(2026, 10, 2))
    ash = next(d for d in deliveries if d.supplier == "ASH")
    assert ash.upload_only and ash.invoice_number == "INV-4471"
    assert next(line for line in ash.lines if line.ingredient == "chicken_thigh").delivered_units == 12
    # Upload-only: nothing booked until the invoice is posted, so Friday starts with no chicken.
    assert world.state.on_hand["chicken_thigh"] == 0


def test_rendered_invoice_is_deterministic_and_reconciles():
    doc = InvoiceDoc(
        supplier=Party("Ashworth Meats Ltd", "Unit 4, Brindle Way, Salford M50 2QP", "GB284551237"),
        customer=Party("The Copper Pot - Manchester", "12 Deansgate, Manchester M3 2BW"),
        number="INV-1", invoice_date=date(2026, 10, 2), delivery_date=date(2026, 10, 2), po_reference="PO-1",
        currency="GBP",
        lines=(DocLine("Chicken thigh", "AM-1", Decimal(12), "kg", "5kg case", Decimal("7.90"), Decimal(0)),
               DocLine("Cola 330ml can", "NG-1", Decimal(2), "case", "24 cans", Decimal("11.04"), Decimal("0.20"))),
    )
    assert render_pdf(doc) == render_pdf(doc)
    ex = doc.extraction()
    assert ex.subtotal == Decimal("116.88") and ex.vat_total == Decimal("4.42") and ex.total == Decimal("121.30")
    assert sum(line.line_total for line in ex.lines) == ex.subtotal


def test_pantry_conversions_are_positive():
    assert all(item.base_qty_per_unit > 0 and item.price > 0 for item in PANTRY.values())
