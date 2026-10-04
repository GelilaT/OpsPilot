"""Supplier documents rendered from templates with realistic layouts (SRS Appendix C).

Output is byte-for-byte deterministic (reportlab invariant mode), so the SHA-256 of a generated file
is stable and the recorded/ground-truth AI responses can be keyed by it. Each document comes with the
extraction a perfect reader would return (Appendix A.2 schema) for the fake AI adapter and the golden
fixture tests.
"""

import hashlib
import io
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from app.ports.ai import Classification, ExtractedLine, ExtractedSupplier, InvoiceExtraction

TWO = Decimal("0.01")


def money(v: Decimal) -> str:
    return f"{v.quantize(TWO, rounding=ROUND_HALF_UP):,.2f}"


def qty_text(v: Decimal) -> str:
    v = v.normalize()
    return f"{v:f}" if v == v.to_integral_value() else f"{v:.2f}"


@dataclass(frozen=True)
class DocLine:
    description: str
    sku: str
    quantity: Decimal
    unit: str
    pack_size: str | None
    unit_price: Decimal  # major units
    vat_rate: Decimal

    @property
    def line_total(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(TWO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Party:
    name: str
    address: str
    vat_number: str | None = None
    email: str | None = None
    phone: str | None = None


@dataclass(frozen=True)
class InvoiceDoc:
    supplier: Party
    customer: Party
    number: str
    invoice_date: date
    delivery_date: date
    po_reference: str | None
    currency: str
    lines: tuple[DocLine, ...]
    payment_days: int = 30
    layout: str = "classic"
    document_title: str = "INVOICE"

    @property
    def due_date(self) -> date:
        return self.invoice_date + timedelta(days=self.payment_days)

    @property
    def subtotal(self) -> Decimal:
        return sum((line.line_total for line in self.lines), Decimal(0))

    def vat_by_rate(self) -> dict[Decimal, Decimal]:
        out: dict[Decimal, Decimal] = {}
        for line in self.lines:
            out[line.vat_rate] = out.get(line.vat_rate, Decimal(0)) + line.line_total
        return {rate: (base * rate).quantize(TWO, rounding=ROUND_HALF_UP) for rate, base in out.items()}

    @property
    def vat_total(self) -> Decimal:
        return sum(self.vat_by_rate().values(), Decimal(0))

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.vat_total

    def extraction(self) -> InvoiceExtraction:
        return InvoiceExtraction(
            supplier=ExtractedSupplier(name=self.supplier.name, vat_number=self.supplier.vat_number,
                                       address=self.supplier.address),
            invoice_number=self.number,
            invoice_date=self.invoice_date.isoformat(),
            delivery_date=self.delivery_date.isoformat(),
            due_date=self.due_date.isoformat(),
            po_reference=self.po_reference,
            currency=self.currency,
            lines=[ExtractedLine(description=line.description, supplier_sku=line.sku, quantity=line.quantity,
                                 unit=line.unit, pack_size=line.pack_size, unit_price=line.unit_price,
                                 line_total=line.line_total, vat_rate=line.vat_rate * 100)
                   for line in self.lines],
            subtotal=self.subtotal, vat_total=self.vat_total, total=self.total,
            field_confidence={"invoice_number": 0.99, "total": 0.99, "lines": 0.97},
        )


# ---------------------------------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------------------------------
def _canvas(buf: io.BytesIO) -> Canvas:
    c = Canvas(buf, pagesize=A4, invariant=1, pageCompression=1)
    c.setAuthor("OpsPilot simulator")
    c.setCreator("OpsPilot simulator")
    return c


def _draw_classic(c: Canvas, doc: InvoiceDoc) -> None:
    w, h = A4
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20 * mm, h - 25 * mm, doc.supplier.name)
    c.setFont("Helvetica", 9)
    y = h - 31 * mm
    for part in [*doc.supplier.address.split(", "), f"VAT Reg No: {doc.supplier.vat_number}",
                 f"{doc.supplier.phone}  ·  {doc.supplier.email}"]:
        c.drawString(20 * mm, y, part)
        y -= 4.5 * mm
    c.setFont("Helvetica-Bold", 22)
    c.drawRightString(w - 20 * mm, h - 25 * mm, doc.document_title)
    c.setFont("Helvetica", 10)
    meta = [("Invoice No", doc.number), ("Invoice Date", doc.invoice_date.strftime("%d/%m/%Y")),
            ("Delivery Date", doc.delivery_date.strftime("%d/%m/%Y")), ("Your Order Ref", doc.po_reference or "-"),
            ("Payment Due", doc.due_date.strftime("%d/%m/%Y"))]
    y = h - 34 * mm
    for k, v in meta:
        c.drawRightString(w - 62 * mm, y, f"{k}:")
        c.drawRightString(w - 20 * mm, y, v)
        y -= 5 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, h - 65 * mm, "Invoice to / Deliver to")
    c.setFont("Helvetica", 10)
    y = h - 70 * mm
    for part in [doc.customer.name, *doc.customer.address.split(", ")]:
        c.drawString(20 * mm, y, part)
        y -= 4.5 * mm
    _table(c, doc, top=h - 95 * mm, cols=[20, 42, 112, 128, 146, 165, 190],
           headers=["Code", "Description", "Pack", "Qty", "Unit Price", "VAT", "Total"])


def _draw_compact(c: Canvas, doc: InvoiceDoc) -> None:
    w, h = A4
    c.setFillColor(colors.HexColor("#1f5f4a"))
    c.rect(0, h - 30 * mm, w, 30 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(15 * mm, h - 15 * mm, doc.supplier.name.upper())
    c.setFont("Helvetica", 8)
    c.drawString(15 * mm, h - 21 * mm, f"{doc.supplier.address}  |  VAT {doc.supplier.vat_number}")
    c.drawString(15 * mm, h - 25 * mm, f"Tel {doc.supplier.phone}  |  {doc.supplier.email}")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(w - 15 * mm, h - 15 * mm, f"TAX {doc.document_title} {doc.number}")
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    c.drawString(15 * mm, h - 40 * mm, f"Customer: {doc.customer.name}")
    c.drawString(15 * mm, h - 45 * mm, doc.customer.address)
    c.drawString(120 * mm, h - 40 * mm, f"Date: {doc.invoice_date.strftime('%d %b %Y')}")
    c.drawString(120 * mm, h - 45 * mm, f"Delivered: {doc.delivery_date.strftime('%d %b %Y')}")
    c.drawString(120 * mm, h - 50 * mm, f"PO: {doc.po_reference or 'n/a'}")
    c.drawString(120 * mm, h - 55 * mm, f"Terms: {doc.payment_days} days - due {doc.due_date.strftime('%d %b %Y')}")
    _table(c, doc, top=h - 65 * mm, cols=[15, 37, 105, 122, 140, 160, 195],
           headers=["SKU", "Item", "Pack", "Qty", "Price", "VAT %", "Net"])


def _draw_modern(c: Canvas, doc: InvoiceDoc) -> None:
    w, h = A4
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 18 * mm, h - 18 * mm, doc.supplier.name)
    y = h - 22 * mm
    for part in doc.supplier.address.split(", "):
        c.drawRightString(w - 18 * mm, y, part)
        y -= 4 * mm
    c.drawRightString(w - 18 * mm, y, f"VAT number {doc.supplier.vat_number}")
    c.setFont("Helvetica-Bold", 28)
    c.drawString(18 * mm, h - 28 * mm, doc.document_title.title())
    c.setFont("Helvetica", 9)
    c.drawString(18 * mm, h - 36 * mm, f"Number  {doc.number}")
    c.drawString(18 * mm, h - 41 * mm, f"Issued  {doc.invoice_date.isoformat()}")
    c.drawString(18 * mm, h - 46 * mm, f"Delivered  {doc.delivery_date.isoformat()}")
    c.drawString(18 * mm, h - 51 * mm, f"Purchase order  {doc.po_reference or '-'}")
    c.drawString(18 * mm, h - 61 * mm, f"Bill to: {doc.customer.name}, {doc.customer.address}")
    _table(c, doc, top=h - 72 * mm, cols=[18, 40, 110, 127, 147, 167, 192],
           headers=["Ref", "Product", "Pack size", "Quantity", "Unit price", "VAT rate", "Amount"])


def _table(c: Canvas, doc: InvoiceDoc, *, top: float, cols: list[int], headers: list[str]) -> None:
    w, _ = A4
    c.setFont("Helvetica-Bold", 9)
    c.line(cols[0] * mm, top + 2 * mm, w - 15 * mm, top + 2 * mm)
    for i, head in enumerate(headers):
        (c.drawString if i < 3 else c.drawRightString)(cols[i] * mm if i < 3 else (cols[i] + 12) * mm, top - 3 * mm, head)
    c.line(cols[0] * mm, top - 5 * mm, w - 15 * mm, top - 5 * mm)
    c.setFont("Helvetica", 9)
    y = top - 10 * mm
    for line in doc.lines:
        c.drawString(cols[0] * mm, y, line.sku)
        c.drawString(cols[1] * mm, y, line.description[:38])
        c.drawString(cols[2] * mm, y, line.pack_size or "")
        c.drawRightString((cols[3] + 12) * mm, y, f"{qty_text(line.quantity)} {line.unit}")
        c.drawRightString((cols[4] + 12) * mm, y, money(line.unit_price))
        c.drawRightString((cols[5] + 12) * mm, y, f"{(line.vat_rate * 100).normalize():f}%")
        c.drawRightString((cols[6] + 12) * mm, y, money(line.line_total))
        y -= 6 * mm
    c.line(cols[0] * mm, y + 2 * mm, w - 15 * mm, y + 2 * mm)
    y -= 4 * mm
    c.setFont("Helvetica", 10)
    right = (cols[6] + 12) * mm
    c.drawRightString(right - 35 * mm, y, "Subtotal")
    c.drawRightString(right, y, money(doc.subtotal))
    for rate, vat in sorted(doc.vat_by_rate().items()):
        y -= 5.5 * mm
        c.drawRightString(right - 35 * mm, y, f"VAT @ {(rate * 100).normalize():f}%")
        c.drawRightString(right, y, money(vat))
    y -= 7 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(right - 35 * mm, y, f"TOTAL {doc.currency}")
    c.drawRightString(right, y, money(doc.total))
    c.setFont("Helvetica", 8)
    c.drawString(cols[0] * mm, 20 * mm, "Goods remain the property of the supplier until paid in full. "
                                        "Please quote the invoice number with payment.")


LAYOUTS = {"classic": _draw_classic, "compact": _draw_compact, "modern": _draw_modern}


def render_pdf(*docs: InvoiceDoc) -> bytes:
    """One page per document (several documents -> a multi-invoice file)."""
    buf = io.BytesIO()
    c = _canvas(buf)
    for doc in docs:
        LAYOUTS[doc.layout](c, doc)
        c.showPage()
    c.save()
    return buf.getvalue()


def render_statement(supplier: Party, customer: Party, rows: list[tuple[date, str, Decimal]], on: date) -> bytes:
    """A monthly statement of account - a supplier document that is not an invoice."""
    buf = io.BytesIO()
    c = _canvas(buf)
    w, h = A4
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20 * mm, h - 25 * mm, supplier.name)
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(w - 20 * mm, h - 25 * mm, "STATEMENT OF ACCOUNT")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, h - 35 * mm, f"Account: {customer.name}")
    c.drawString(20 * mm, h - 40 * mm, f"Statement date: {on.strftime('%d/%m/%Y')}")
    y = h - 55 * mm
    c.setFont("Helvetica-Bold", 10)
    for x, head in ((20, "Date"), (50, "Reference"), (150, "Amount")):
        c.drawString(x * mm, y, head)
    c.setFont("Helvetica", 10)
    balance = Decimal(0)
    for d, ref, amount in rows:
        y -= 6 * mm
        balance += amount
        c.drawString(20 * mm, y, d.strftime("%d/%m/%Y"))
        c.drawString(50 * mm, y, f"Invoice {ref}")
        c.drawRightString(170 * mm, y, money(amount))
    y -= 10 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50 * mm, y, "Balance outstanding")
    c.drawRightString(170 * mm, y, money(balance))
    c.drawString(20 * mm, 30 * mm, "This is a statement, not a VAT invoice. Do not pay from this document.")
    c.showPage()
    c.save()
    return buf.getvalue()


def photograph(pdf: bytes, seed: str) -> bytes:
    """Render page 1 and make it look like a phone photo: slight rotation, warm cast, blur, noise, JPEG."""
    import pymupdf as fitz
    from PIL import Image, ImageFilter

    r = random.Random(seed)
    page = fitz.open(stream=pdf, filetype="pdf")[0]
    pix = page.get_pixmap(dpi=110)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    canvas = Image.new("RGB", (int(img.width * 1.12), int(img.height * 1.08)), (92, 84, 72))
    canvas.paste(img, (int(img.width * 0.05), int(img.height * 0.03)))
    canvas = canvas.rotate(r.uniform(-2.5, 2.5), resample=Image.Resampling.BICUBIC, fillcolor=(92, 84, 72))
    warm = Image.new("RGB", canvas.size, (255, 236, 205))
    canvas = Image.blend(canvas, warm, 0.10).filter(ImageFilter.GaussianBlur(0.6))
    noise = Image.effect_noise(canvas.size, 12).convert("RGB")
    canvas = Image.blend(canvas, noise, 0.05)
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=82, optimize=False)
    return out.getvalue()


@dataclass
class GeneratedDocument:
    filename: str
    content: bytes
    mime: str
    classification: Classification
    extraction: InvoiceExtraction | None
    description: str
    meta: dict = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def write_documents(docs: list[GeneratedDocument], out_dir: Path, ai_fixture_dir: Path) -> None:
    """Write files for the demo plus ground-truth AI fixtures keyed by SHA-256."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ai_fixture_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for d in docs:
        (out_dir / d.filename).write_bytes(d.content)
        fixture = {"sha256": d.sha256, "filename": d.filename,
                   "classification": d.classification.model_dump(mode="json"),
                   "extraction": d.extraction.model_dump(mode="json") if d.extraction else None}
        (ai_fixture_dir / f"{d.sha256}.json").write_text(json.dumps(fixture, indent=1))
        manifest.append({"file": d.filename, "sha256": d.sha256, "description": d.description, **d.meta})
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
