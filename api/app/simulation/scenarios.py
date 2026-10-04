"""Demonstration scenarios planted on fixed dates (SRS Table 15). Same seed -> same data."""

from datetime import date
from decimal import Decimal as D

from app.simulation.profile import (
    InvoiceNumberAnchor,
    ParChange,
    PriceEvent,
    ShortDelivery,
    Spoilage,
    UploadOnlyDelivery,
)

SEED_END = date(2026, 10, 1)  # Thursday; "simulate next day" continues from Friday 2 October
SEED_DAYS = 120

CP, CP1 = "copper-pot", "CP1"
NK = "northside-kitchens"

PRICE_EVENTS: tuple[PriceEvent, ...] = (
    # S1: Supplier A raises chicken thigh from 6.70 to 7.90 per kg (+18%) on INV-4471
    PriceEvent(CP, "ASH", "chicken_thigh", date(2026, 10, 2), D("7.90")),
    # Tortilla wraps 0.28 -> 0.34 each (explains the other 20% of the Chicken Wrap cost increase)
    PriceEvent(CP, "CFS", "tortilla_wraps", date(2026, 9, 15), D("6.12")),
)

SHORT_DELIVERIES: tuple[ShortDelivery, ...] = (
    # S7: a similar short delivery on 19 Sep (recalled from memory in the S2 investigation)
    ShortDelivery(CP, CP1, "ASH", "chicken_thigh", date(2026, 9, 19), D(20), D(14)),
    # S2: INV-4471 delivers 12 kg against a PO for 20 kg
    ShortDelivery(CP, CP1, "ASH", "chicken_thigh", date(2026, 10, 2), D(20), D(12)),
)

UPLOAD_ONLY: tuple[UploadOnlyDelivery, ...] = (
    # Booked into stock only when the invoice is uploaded, approved and posted (demo flow 1)
    UploadOnlyDelivery(CP, CP1, "ASH", date(2026, 10, 2), layout="classic"),
    UploadOnlyDelivery(NK, "NK-LDS", "KMP", date(2026, 10, 2), layout="compact"),
    UploadOnlyDelivery(NK, "NK-YRK", "WHD", date(2026, 10, 2), layout="modern"),
)

SPOILAGE: tuple[Spoilage, ...] = (
    # Remaining chicken binned at close on Thursday, so Friday depends entirely on INV-4471
    Spoilage(CP, CP1, "chicken_thigh", date(2026, 10, 1)),
)

INVOICE_ANCHORS: tuple[InvoiceNumberAnchor, ...] = (
    InvoiceNumberAnchor(CP, CP1, "ASH", date(2026, 10, 2), "INV-", 4471),
)

PAR_CHANGES: tuple[ParChange, ...] = (
    ParChange(CP, CP1, "chicken_thigh", date(2026, 9, 21), D(18000),
              "Raised from 15 kg to 18 kg after the 19 Sep short delivery from Ashworth Meats"),
)

SCENARIO_CATALOGUE = {
    "S1": "Supplier A raises chicken thigh from 6.70 to 7.90 per kg (+18%) on INV-4471",
    "S2": "INV-4471 delivers 12 kg against a PO for 20 kg; stock-out on Friday evening",
    "S3": "Supplier B offers chicken thigh at 7.19 per kg with 97% fill rate",
    "S4": "The same invoice uploaded twice and re-photographed",
    "S7": "A similar short delivery on 19 Sep",
}


def for_org(items, org: str):
    return [i for i in items if i.org == org]
