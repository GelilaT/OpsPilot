"""Demo and golden supplier documents (S4 and flow 1), rendered from the simulator's next deliveries.

Copper Pot: INV-4471 (S1/S2: +18% chicken, 12 of 20 kg), the same invoice re-photographed (S4) and a
supplier statement (not an invoice). Northside Kitchens: today's produce invoice for Leeds, today's dairy
invoice for York and a file containing two invoices.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.ports.ai import Classification
from app.simulation.catalogue import Catalogue, rng
from app.simulation.invoice_render import (
    DocLine,
    GeneratedDocument,
    InvoiceDoc,
    Party,
    photograph,
    render_pdf,
    render_statement,
)
from app.simulation.profile import OrgProfile, SiteSpec
from app.simulation.world import Delivery, SiteWorld


def invoice_doc(cat: Catalogue, site: SiteSpec, delivery: Delivery, layout: str) -> InvoiceDoc:
    spec = cat.suppliers[delivery.supplier]
    lines = []
    for line in delivery.lines:
        if line.delivered_units <= 0:
            continue
        product = cat.products[(delivery.supplier, line.ingredient)]
        lines.append(DocLine(product.name, product.sku, line.delivered_units, product.purchase_unit,
                             product.pack_size, Decimal(line.unit_price_minor) / 100, product.vat_rate))
    return InvoiceDoc(
        supplier=Party(spec.name, spec.address, spec.vat_number, spec.email, spec.phone),
        customer=Party(site.name, site.address),
        number=delivery.invoice_number, invoice_date=delivery.business_date, delivery_date=delivery.business_date,
        po_reference=delivery.po_number, currency=cat.org.currency, lines=tuple(lines), layout=layout,
        payment_days=30 if delivery.supplier not in ("FFP", "KMP") else 14,
    )


def _invoice(doc: InvoiceDoc, filename: str, description: str, **meta) -> GeneratedDocument:
    return GeneratedDocument(
        filename=filename, content=render_pdf(doc), mime="application/pdf",
        classification=Classification(document_type="invoice", confidence=0.97, multiple_documents=False,
                                      reason="Supplier tax invoice with line items, VAT and total"),
        extraction=doc.extraction(), description=description,
        meta={"supplier": doc.supplier.name, "number": doc.number, "total": str(doc.total), **meta},
    )


def copper_pot_documents(org: OrgProfile, cat: Catalogue, worlds: dict[str, SiteWorld], day: date,
                         preview) -> list[GeneratedDocument]:
    site = org.sites[0]
    deliveries = {d.supplier: d for d in preview(worlds[site.code], day)}
    inv4471 = invoice_doc(cat, site, deliveries["ASH"], "classic")
    pdf = _invoice(inv4471, "INV-4471.pdf",
                   "S1/S2: Ashworth Meats - chicken thigh 7.90/kg (+18%), 12 kg delivered against a 20 kg PO",
                   scenario="S1,S2", upload_order=1)
    photo = GeneratedDocument(
        filename="INV-4471-photo.jpg", content=photograph(pdf.content, "INV-4471"), mime="image/jpeg",
        classification=Classification(document_type="invoice", confidence=0.91, multiple_documents=False,
                                      reason="Photograph of a supplier invoice"),
        extraction=inv4471.extraction(),
        description="S4: the same invoice re-photographed (possible_duplicate: same supplier and number)",
        meta={"supplier": inv4471.supplier.name, "number": inv4471.number, "scenario": "S4", "upload_order": 3},
    )
    cfs = cat.suppliers["CFS"]
    r = rng(org.slug, "statement")
    rows = []
    d = day - timedelta(days=30)
    while d < day:
        if d.weekday() in cfs.delivery_weekdays:
            rows.append((d, cat.invoice_number(site, "CFS", d), Decimal(r.randint(18000, 42000)) / 100))
        d += timedelta(days=1)
    statement = GeneratedDocument(
        filename="castlefield-statement.pdf",
        content=render_statement(Party(cfs.name, cfs.address, cfs.vat_number), Party(site.name, site.address), rows, day),
        mime="application/pdf",
        classification=Classification(document_type="statement", confidence=0.95, multiple_documents=False,
                                      reason="Statement of account listing several invoices; not a VAT invoice"),
        extraction=None, description="Not an invoice: a supplier statement (ends in not_invoice)",
        meta={"supplier": cfs.name, "upload_order": 4},
    )
    pdf.meta["note"] = "Upload this file twice to see the exact duplicate (S4, SHA-256)."
    return [pdf, photo, statement]


def northside_documents(org: OrgProfile, cat: Catalogue, worlds: dict[str, SiteWorld], day: date,
                        preview) -> list[GeneratedDocument]:
    leeds, york = org.sites
    leeds_deliveries = {d.supplier: d for d in preview(worlds[leeds.code], day)}
    york_deliveries = {d.supplier: d for d in preview(worlds[york.code], day)}
    produce = invoice_doc(cat, leeds, leeds_deliveries["KMP"], "compact")
    dairy = invoice_doc(cat, york, york_deliveries["WHD"], "modern")
    docs = [
        _invoice(produce, f"{leeds.code}-produce-{produce.number}.pdf",
                 "Leeds: today's produce invoice (compact layout)", site=leeds.code, upload_order=1),
        _invoice(dairy, f"{york.code}-dairy-{dairy.number}.pdf",
                 "York: today's dairy invoice (modern layout)", site=york.code, upload_order=1),
    ]
    pair = [invoice_doc(cat, leeds, leeds_deliveries[s], layout)
            for s, layout in (("KIR", "classic"), ("AVF", "modern")) if s in leeds_deliveries]
    if len(pair) == 2:
        docs.append(GeneratedDocument(
            filename=f"{leeds.code}-two-invoices.pdf", content=render_pdf(*pair), mime="application/pdf",
            classification=Classification(document_type="invoice", confidence=0.82, multiple_documents=True,
                                          reason="File contains two separate supplier invoices"),
            extraction=pair[0].extraction(),
            description="Leeds: one file with two invoices (multiple_documents -> needs_review)",
            meta={"site": leeds.code, "numbers": [p.number for p in pair], "upload_order": 2},
        ))
    return docs
