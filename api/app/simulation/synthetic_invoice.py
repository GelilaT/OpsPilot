"""Synthetic supplier invoices for demos (FR-INV-01 POST /invoices/simulate).

Built from the site's own catalogue and latest prices, so it works for any organisation. The ground
truth extraction is recorded for the offline AI adapter; with Gemini the model reads the rendered file.
"""

import asyncio
import json
import random
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Unprocessable
from app.domain.purchasing.models import PriceObservation, Supplier, SupplierProduct
from app.ports.ai import Classification
from app.simulation.invoice_render import DocLine, InvoiceDoc, Party, render_pdf

LAYOUTS = ("classic", "compact", "modern")


@dataclass
class SyntheticInvoice:
    filename: str
    content: bytes
    sha256: str
    supplier: str
    number: str
    total: Decimal


async def build_synthetic_invoice(session: AsyncSession, *, site_id: uuid.UUID, site_name: str, site_address: str,
                                  currency: str, today: date, supplier_id: uuid.UUID | None = None,
                                  price_change_pct: Decimal = Decimal(0), seed: int | None = None,
                                  fixtures_dir: Path | None = None) -> SyntheticInvoice:
    r = random.Random(seed)
    q = select(Supplier).where(Supplier.active.is_(True))
    suppliers = [s for s in (await session.execute(q)).scalars() if supplier_id is None or s.id == supplier_id]
    if not suppliers:
        raise Unprocessable("No supplier is available to simulate an invoice.", code="no_supplier")
    supplier = r.choice(suppliers)
    latest = dict((await session.execute(
        select(PriceObservation.supplier_product_id, PriceObservation.unit_price_minor)
        .where(PriceObservation.site_id == site_id, PriceObservation.supplier_id == supplier.id)
        .ext(distinct_on(PriceObservation.supplier_product_id))
        .order_by(PriceObservation.supplier_product_id, PriceObservation.observed_on.desc()))).all())
    products = [p for p in (await session.execute(select(SupplierProduct).where(
        SupplierProduct.supplier_id == supplier.id, SupplierProduct.active.is_(True)))).scalars() if p.id in latest]
    if not products:
        raise Unprocessable(f"{supplier.name} has no priced products at this site.", code="no_products")
    chosen = r.sample(products, k=min(len(products), r.randint(3, 6)))
    lines = []
    for p in sorted(chosen, key=lambda p: p.sku):
        price = (Decimal(latest[p.id]) * (1 + price_change_pct) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        lines.append(DocLine(p.name, p.sku, Decimal(r.randint(1, 6)), p.purchase_unit, p.pack_size, price,
                             Decimal(p.vat_rate)))
    number = f"SIM-{today:%y%m%d}-{r.randint(1000, 9999)}"
    doc = InvoiceDoc(
        supplier=Party(supplier.name, supplier.address or "", supplier.vat_number, supplier.email, supplier.phone),
        customer=Party(site_name, site_address or ""), number=number, invoice_date=today, delivery_date=today,
        po_reference=None, currency=currency, lines=tuple(lines), layout=r.choice(LAYOUTS),
        payment_days=30, document_title="INVOICE",
    )
    content = render_pdf(doc)
    import hashlib

    sha = hashlib.sha256(content).hexdigest()
    if fixtures_dir is not None:
        await asyncio.to_thread(_write_fixture, fixtures_dir, sha, number, doc)
    return SyntheticInvoice(f"{number}.pdf", content, sha, supplier.name, number, doc.total)


def _write_fixture(fixtures_dir: Path, sha: str, number: str, doc: InvoiceDoc) -> None:
    """Ground truth for the offline AI adapter (keyed by SHA-256)."""
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    (fixtures_dir / f"{sha}.json").write_text(json.dumps({
        "sha256": sha, "filename": f"{number}.pdf",
        "classification": Classification(document_type="invoice", confidence=0.97, multiple_documents=False,
                                         reason="Synthetic supplier invoice").model_dump(mode="json"),
        "extraction": doc.extraction().model_dump(mode="json")}, indent=1))


_ = timedelta
