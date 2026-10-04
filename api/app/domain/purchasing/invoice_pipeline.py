"""InvoicePipeline (SRS S4, Table 62): a durable workflow that moves an InvoiceDocument from `received`
to a terminal or review state. AI output is an untrusted proposal: it is schema-validated, then every
number is recomputed or checked in Python before anything reaches inventory or prices.

Steps commit separately so no database transaction is held open during an AI call. Every step is
idempotent: re-running the job resumes from the document's current state.
"""

import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.errors import Conflict
from app.core.jobs import enqueue, job_key
from app.core.ratelimit import acquire_ai_slot
from app.core.settings import get_settings
from app.core.tenancy.context import SiteContext
from app.core.uom import UnknownConversion
from app.domain.purchasing.invoice_models import (
    AICall,
    Invoice,
    InvoiceDocument,
    InvoiceException,
    InvoiceLine,
    InvoiceTransition,
)
from app.domain.purchasing.invoice_rules import (
    POLICY,
    HeaderValues,
    Issue,
    LineValues,
    PriceCheckInput,
    can_transition,
    check_against_po,
    check_price,
    normalise_invoice_number,
    parse_date,
    parse_decimal,
    parse_vat_rate,
    qty_base_for,
    to_minor,
    unit_price_minor,
    validate,
)
from app.domain.purchasing.matching import ProductInfo, match_line, match_supplier, price_history, supplier_products
from app.domain.purchasing.models import GoodsReceipt, GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine, Supplier
from app.ports import IntegrationKind
from app.ports.ai import AICallInfo, Classification, InvoiceExtraction
from app.ports.errors import PortError, RateLimitedError, TransientError

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 10
MIN_IMAGE_BYTES = 8 * 1024
EXTENSIONS = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
              "image/heic": ".heic", "image/heif": ".heif"}
SYSTEM_ACTOR = "system:invoice-pipeline"


# ---------------------------------------------------------------------------------------------------
# File gates (FR-INV-02/03)
# ---------------------------------------------------------------------------------------------------
def sniff_mime(data: bytes) -> str | None:
    """Detect the type from the bytes, never from the file name or the client's Content-Type."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis"):
            return "image/heic"
        if brand in (b"mif1", b"msf1", b"avif"):
            return "image/heif" if brand != b"avif" else None
    return None


def pdf_page_count(data: bytes) -> int | None:
    import pymupdf

    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return doc.page_count
    except Exception:
        return None


def heic_to_jpeg(data: bytes) -> bytes:
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    img = Image.open(io.BytesIO(data)).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


# ---------------------------------------------------------------------------------------------------
# State machine (FR-INV-13)
# ---------------------------------------------------------------------------------------------------
async def transition(session: AsyncSession, doc: InvoiceDocument, to: str, *, actor: str, reason: str,
                     invoice: Invoice | None = None) -> None:
    if not can_transition(doc.state, to):
        raise Conflict(f"An invoice in state {doc.state!r} cannot move to {to!r}.", code="illegal_transition",
                       extra={"from": doc.state, "to": to})
    before = doc.state
    doc.state = to
    doc.version += 1
    if invoice is not None:
        invoice.status = to
    session.add(InvoiceTransition(organisation_id=doc.organisation_id, site_id=doc.site_id, document_id=doc.id,
                                  from_state=before, to_state=to, actor=actor, reason=reason[:600]))
    record_audit(session, actor=actor, entity_type="invoice_document", entity_id=doc.id, action=f"state:{to}",
                 organisation_id=doc.organisation_id, site_id=doc.site_id, before={"state": before},
                 after={"state": to, "reason": reason[:300]})


# ---------------------------------------------------------------------------------------------------
# Intake (FR-INV-01/02/03)
# ---------------------------------------------------------------------------------------------------
async def intake(ctx: SiteContext, *, filename: str, content: bytes, actor: str, source: str = "upload") -> InvoiceDocument:
    """Store the original, create the InvoiceDocument and enqueue processing (or fail it at the gates)."""
    sha = hashlib.sha256(content).hexdigest()
    mime = sniff_mime(content)
    original = (await ctx.session.execute(select(InvoiceDocument).where(
        InvoiceDocument.site_id == ctx.site_id, InvoiceDocument.sha256 == sha,
        InvoiceDocument.duplicate_of_id.is_(None), InvoiceDocument.state != "failed"))).scalar_one_or_none()
    doc = InvoiceDocument(id=uuid.uuid4(), organisation_id=ctx.organisation_id, site_id=ctx.site_id, sha256=sha,
                          filename=filename[:300] or "upload", mime=mime or "application/octet-stream",
                          size_bytes=len(content), source=source, state="received", uploaded_by=actor, version=1,
                          duplicate_of_id=original.id if original is not None else None)
    ctx.session.add(doc)
    ctx.session.add(InvoiceTransition(organisation_id=doc.organisation_id, site_id=doc.site_id, document_id=doc.id,
                                      from_state=None, to_state="received", actor=actor, reason=f"{source}: {filename}"))
    await ctx.session.flush()
    record_audit(ctx.session, actor=actor, entity_type="invoice_document", entity_id=doc.id, action="upload",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                 after={"filename": filename, "sha256": sha, "mime": mime, "size_bytes": len(content), "source": source})

    reason = None
    if len(content) > MAX_BYTES:
        reason = f"The file is {len(content) / 1_048_576:.1f} MB; the limit is 20 MB."
    elif mime is None:
        reason = "Unsupported file type. Upload a PDF, JPEG, PNG, WebP or HEIC file."
    elif mime == "application/pdf":
        pages = pdf_page_count(content)
        doc.pages = pages
        if pages is None:
            reason = "The PDF could not be read (corrupt or password-protected)."
        elif pages > MAX_PAGES:
            reason = f"The PDF has {pages} pages; the limit is {MAX_PAGES}."
    elif len(content) < MIN_IMAGE_BYTES:
        reason = "The image is smaller than 8 KB - it looks like a logo, not an invoice."
    else:
        doc.pages = 1
    if reason:
        doc.failure_reason, doc.duplicate_of_id = reason, None
        await transition(ctx.session, doc, "failed", actor=actor, reason=reason)
        return doc

    if original is not None:  # exact duplicate (same site + SHA-256): no AI call, linked to the original
        await transition(ctx.session, doc, "duplicate", actor=actor,
                         reason=f"Exact duplicate of {original.filename} uploaded {original.created_at:%d %b %Y %H:%M}.")
        return doc

    storage = await ctx.adapter(IntegrationKind.storage)
    base = f"org/{ctx.organisation_id}/site/{ctx.site_id}/invoices/{sha}"
    assert mime is not None
    doc.storage_key = await storage.put(content, key=base + EXTENSIONS[mime], content_type=mime)
    if mime in ("image/heic", "image/heif"):
        doc.preview_key = await storage.put(heic_to_jpeg(content), key=base + "-preview.jpg", content_type="image/jpeg")
    await enqueue_processing(ctx.session, doc)
    return doc


async def enqueue_processing(session: AsyncSession, doc: InvoiceDocument) -> None:
    await enqueue(session, "invoice.process", key=job_key("invoice.process", doc.id, doc.version), lock=f"invoice:{doc.id}",
                  args={"organisation_id": str(doc.organisation_id), "site_id": str(doc.site_id),
                        "document_id": str(doc.id)})


# ---------------------------------------------------------------------------------------------------
# AI steps (FR-INV-04/05/17)
# ---------------------------------------------------------------------------------------------------
@dataclass
class AIOutcome:
    classification: Classification | None = None
    extraction: InvoiceExtraction | None = None
    info: AICallInfo | None = None


async def ai_slot(ctx: SiteContext, ai: Any) -> None:
    """Shared token bucket (FR-JOB-07). Raises RateLimitedError so the job defers without using a retry."""
    if getattr(ai, "provider", "") != "gemini":
        return
    s = get_settings()
    wait = await acquire_ai_slot(ctx.session, per_minute=s.ai_requests_per_minute, per_day=s.ai_requests_per_day)
    if wait:
        raise RateLimitedError("Local AI budget exhausted", retry_after=max(1.0, wait), provider="gemini")


def log_ai_call(ctx: SiteContext, doc: InvoiceDocument, purpose: str, ai: Any, info: AICallInfo | None,
                outcome: str, detail: str | None = None) -> None:
    ctx.session.add(AICall(organisation_id=ctx.organisation_id, site_id=ctx.site_id, document_id=doc.id,
                           purpose=purpose, provider=getattr(ai, "provider", "?"),
                           model=info.model if info else getattr(ai, "model", "?"),
                           latency_ms=info.latency_ms if info else None,
                           input_tokens=info.input_tokens if info else None,
                           output_tokens=info.output_tokens if info else None,
                           outcome=outcome, detail=(detail or "")[:400] or None))


def outcome_of(exc: Exception) -> str:
    if isinstance(exc, RateLimitedError):
        return "rate_limited"
    if isinstance(exc, TransientError):
        return "transient"
    return "permanent"


def apply_classification(ctx: SiteContext, doc: InvoiceDocument, c: Classification) -> tuple[str, str, Issue | None]:
    """invoice + single + confident -> extracting; other confident types -> not_invoice; else review."""
    threshold = float(ctx.config.get("invoice.classification_min_confidence"))
    doc.doc_type, doc.confidence = c.document_type, Decimal(str(round(c.confidence, 3)))
    doc.multiple_documents, doc.classification_reason = c.multiple_documents, c.reason[:300]
    if c.document_type == "invoice" and not c.multiple_documents and c.confidence >= threshold:
        return "extracting", f"Classified as an invoice ({c.confidence:.0%}).", None
    if c.document_type != "invoice" and c.confidence >= threshold and not c.multiple_documents:
        return "not_invoice", f"Classified as {c.document_type.replace('_', ' ')} ({c.confidence:.0%}): {c.reason}", None
    why = ("The file contains more than one document" if c.multiple_documents
           else f"Low classification confidence ({c.confidence:.0%}, threshold {threshold:.0%})")
    issue = Issue("low_confidence", "warning", f"{why}. Please check it is a single supplier invoice.",
                  {"document_type": c.document_type, "confidence": c.confidence,
                   "multiple_documents": c.multiple_documents, "reason": c.reason, "threshold": threshold})
    return "needs_review", why + ".", issue


# ---------------------------------------------------------------------------------------------------
# Building the invoice from the extraction
# ---------------------------------------------------------------------------------------------------
def build_invoice(ctx: SiteContext, doc: InvoiceDocument, ex: InvoiceExtraction) -> tuple[Invoice, list[InvoiceLine]]:
    currency = (ex.currency or ctx.currency or "").upper().strip() or None
    cur = currency or ctx.currency
    invoice = Invoice(
        id=uuid.uuid4(), organisation_id=ctx.organisation_id, site_id=ctx.site_id, document_id=doc.id,
        source=doc.source, status=doc.state, supplier_name=(ex.supplier.name or None),
        supplier_vat_number=ex.supplier.vat_number, supplier_address=ex.supplier.address, number=ex.invoice_number,
        normalised_number=normalise_invoice_number(ex.invoice_number), invoice_date=parse_date(ex.invoice_date),
        delivery_date=parse_date(ex.delivery_date), due_date=parse_date(ex.due_date), po_reference=ex.po_reference,
        currency=currency, ai_subtotal_minor=to_minor(ex.subtotal, cur), ai_vat_minor=to_minor(ex.vat_total, cur),
        ai_total_minor=to_minor(ex.total, cur), version=1,
    )
    lines = [InvoiceLine(
        id=uuid.uuid4(), organisation_id=ctx.organisation_id, site_id=ctx.site_id, invoice_id=invoice.id, line_no=n,
        raw_description=(line.description or "")[:400], supplier_sku=line.supplier_sku,
        quantity=parse_decimal(line.quantity), uom=line.unit, pack_size=line.pack_size,
        unit_price_minor=unit_price_minor(parse_decimal(line.unit_price), cur),
        line_total_minor=to_minor(parse_decimal(line.line_total), cur), vat_rate=parse_vat_rate(line.vat_rate),
    ) for n, line in enumerate(ex.lines, start=1)]
    return invoice, lines


# ---------------------------------------------------------------------------------------------------
# Evaluation: validate -> match -> price / PO / duplicate checks -> exceptions -> review or approval
# ---------------------------------------------------------------------------------------------------
async def evaluate(ctx: SiteContext, doc: InvoiceDocument, invoice: Invoice, *, actor: str, reason: str) -> list[Issue]:
    session = ctx.session
    cfg = ctx.config
    lines = list((await session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)
                                        .order_by(InvoiceLine.line_no))).scalars())
    issues: list[Issue] = []

    # Supplier (FR-INV-08)
    if invoice.supplier_id is None:
        sm = await match_supplier(session, name=invoice.supplier_name, vat_number=invoice.supplier_vat_number,
                                  threshold=float(cfg.get("invoice.supplier_name_similarity")))
        invoice.supplier_id = sm.supplier_id
        if sm.supplier_id is None and (invoice.supplier_name or invoice.supplier_vat_number):
            issues.append(Issue("unknown_supplier", "warning",
                                f"Supplier {invoice.supplier_name!r} is not in the catalogue. Choose the supplier "
                                "or add it before approval.",
                                {"name": invoice.supplier_name, "vat_number": invoice.supplier_vat_number,
                                 "candidates": sm.candidates}))

    # Lines (FR-INV-07/09)
    products: list[ProductInfo] = []
    if invoice.supplier_id is not None:
        products = await supplier_products(session, ctx.site_id, invoice.supplier_id)
    by_id = {p.id: p for p in products}
    for line in lines:
        if line.non_stock:
            line.qty_base = line.price_per_base_minor = None
            continue
        if invoice.supplier_id is None:
            line.supplier_product_id = line.ingredient_id = None
            continue
        product = by_id.get(line.supplier_product_id) if line.match_method == "manual" and line.supplier_product_id else None
        if product is None:
            m = await match_line(session, supplier_id=invoice.supplier_id, products=products,
                                 description=line.raw_description, sku=line.supplier_sku, uom=line.uom,
                                 pack_size=line.pack_size, line_total_minor=line.line_total_minor, quantity=line.quantity,
                                 auto=float(cfg.get("invoice.line_auto_match")),
                                 suggest=float(cfg.get("invoice.line_suggest_match")))
            product, line.match_method = m.product, m.method
            line.match_confidence = Decimal(str(round(m.score, 3)))
            line.match_candidates = m.candidates or None
        if product is None:
            line.supplier_product_id = line.ingredient_id = line.qty_base = line.price_per_base_minor = None
            issues.append(Issue("unmatched_line", "warning",
                                f"Line {line.line_no} ({line.raw_description!r}) does not match a product of this "
                                "supplier. Map it or mark it non-stock.",
                                {"description": line.raw_description, "sku": line.supplier_sku,
                                 "best_score": float(line.match_confidence or 0), "candidates": line.match_candidates or []},
                                line_no=line.line_no))
            continue
        line.supplier_product_id, line.ingredient_id = product.id, product.ingredient_id
        try:
            if line.quantity is None:
                raise UnknownConversion("no quantity")
            line.qty_base = qty_base_for(line.quantity, line.uom, line.pack_size, base_unit=product.base_unit,
                                         purchase_unit=product.purchase_unit,
                                         base_qty_per_unit=product.base_qty_per_unit, conversions=product.conversions)
            qty_base = line.qty_base
            line.price_per_base_minor = (Decimal(line.line_total_minor) / qty_base).quantize(Decimal("0.000001")) \
                if qty_base and line.line_total_minor is not None else None
        except UnknownConversion:
            line.qty_base = line.price_per_base_minor = None
            if line.quantity is not None:
                issues.append(Issue("unmatched_unit", "warning",
                                    f"Line {line.line_no}: no conversion from {line.uom!r} to {product.base_unit} for "
                                    f"{product.name}.", {"unit": line.uom, "pack_size": line.pack_size,
                                                         "base_unit": product.base_unit, "product": product.name},
                                    line_no=line.line_no))

    # Deterministic validation and recomputed totals (FR-INV-06)
    header = HeaderValues(invoice.supplier_name, invoice.supplier_id is not None, invoice.number, invoice.invoice_date,
                          invoice.currency, invoice.ai_subtotal_minor, invoice.ai_vat_minor, invoice.ai_total_minor)
    values = [LineValues(line.line_no, line.raw_description, line.quantity, line.unit_price_minor,
                         line.line_total_minor, line.vat_rate, line.non_stock) for line in lines]
    found, totals = validate(header, values, today=await ctx.today(),
                             max_future_days=int(cfg.get("invoice.max_future_days")),
                             max_age_months=int(cfg.get("invoice.max_age_months")))
    issues.extend(found)
    invoice.subtotal_minor, invoice.vat_minor, invoice.total_minor = totals.subtotal_minor, totals.vat_minor, totals.total_minor
    invoice.normalised_number = normalise_invoice_number(invoice.number)

    if invoice.supplier_id is not None:
        issues.extend(await _price_checks(ctx, invoice, lines, by_id))
        issues.extend(await _po_checks(ctx, invoice, lines, by_id))
        issues.extend(await _duplicate_checks(ctx, invoice))

    await save_exceptions(session, doc, invoice, issues, {line.line_no: line.id for line in lines})
    await settle_state(ctx, doc, invoice, actor=actor, reason=reason)
    return issues


async def _price_checks(ctx: SiteContext, invoice: Invoice, lines: list[InvoiceLine],
                        products: dict[uuid.UUID, ProductInfo]) -> list[Issue]:
    """FR-INV-10: vs the last price and the 90-day median; contract price breaches."""
    cfg = ctx.config
    out: list[Issue] = []
    as_of = invoice.invoice_date or await ctx.today()
    for line in lines:
        product = products.get(line.supplier_product_id) if line.supplier_product_id else None
        if product is None or line.price_per_base_minor is None or not line.qty_base:
            continue
        history = await price_history(ctx.session, ctx.site_id, product.id, as_of, str(invoice.id))
        contract = None
        if product.contract_price_minor is not None and (product.contract_valid_until is None
                                                         or as_of <= product.contract_valid_until):
            contract = Decimal(product.contract_price_minor) / product.base_qty_per_unit
        for issue in check_price(
            PriceCheckInput(Decimal(line.price_per_base_minor), Decimal(line.qty_base), product.base_unit, history, contract),
            pct=float(cfg.get("invoice.price_increase_pct")),
            min_abs_per_unit_minor=int(cfg.get("invoice.price_increase_min_per_unit_minor")),
            robust_z=float(cfg.get("invoice.price_robust_z")),
            warning_minor=int(cfg.get("detection.severity_warning_minor")),
            critical_minor=int(cfg.get("detection.severity_critical_minor")), as_of=as_of,
        ):
            issue.line_no = line.line_no
            issue.facts.update({"product": product.name, "line": line.line_no})
            issue.message = f"Line {line.line_no} ({product.name}): {issue.message}"
            out.append(issue)
    return out


async def _po_checks(ctx: SiteContext, invoice: Invoice, lines: list[InvoiceLine],
                     products: dict[uuid.UUID, ProductInfo]) -> list[Issue]:
    """FR-INV-11: invoiced vs ordered (PO) and vs received (goods receipt)."""
    session, cfg = ctx.session, ctx.config
    po = None
    if invoice.po_reference:
        po = (await session.execute(select(PurchaseOrder).where(
            PurchaseOrder.site_id == ctx.site_id, PurchaseOrder.number == invoice.po_reference.strip()))).scalar_one_or_none()
    delivered_on = invoice.delivery_date or invoice.invoice_date
    if po is None and delivered_on is not None:
        po = (await session.execute(select(PurchaseOrder).where(
            PurchaseOrder.site_id == ctx.site_id, PurchaseOrder.supplier_id == invoice.supplier_id,
            PurchaseOrder.expected_delivery_date == delivered_on,
            PurchaseOrder.status.in_(("committed", "sent", "part_received", "received"))))).scalars().first()
    if po is None or po.supplier_id != invoice.supplier_id:
        invoice.purchase_order_id = None
        return []
    invoice.purchase_order_id = po.id
    gr = (await session.execute(select(GoodsReceipt).where(
        GoodsReceipt.site_id == ctx.site_id, GoodsReceipt.purchase_order_id == po.id))).scalars().first()
    invoice.goods_receipt_id = gr.id if gr else None
    po_lines = {pl.ingredient_id: pl for pl in (await session.execute(select(PurchaseOrderLine).where(
        PurchaseOrderLine.purchase_order_id == po.id))).scalars()}
    received: dict[uuid.UUID, Decimal] = {}
    if gr is not None:
        for gl in (await session.execute(select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == gr.id))).scalars():
            received[gl.ingredient_id] = received.get(gl.ingredient_id, Decimal(0)) + Decimal(gl.qty_base)
    out: list[Issue] = []
    for line in lines:
        product = products.get(line.supplier_product_id) if line.supplier_product_id else None
        if product is None or line.qty_base is None or line.price_per_base_minor is None:
            continue
        pl = po_lines.get(product.ingredient_id)
        if pl is None:
            continue
        out.extend(check_against_po(
            line_no=line.line_no, description=product.name, invoiced_base=Decimal(line.qty_base),
            invoiced_price_per_base=Decimal(line.price_per_base_minor), ordered_base=Decimal(pl.qty_base),
            received_base=received.get(product.ingredient_id),
            po_price_per_base=Decimal(pl.unit_price_minor) / product.base_qty_per_unit,
            unit_size_base=product.base_qty_per_unit, base_unit=product.base_unit, po_number=po.number,
            qty_tolerance=float(cfg.get("invoice.qty_tolerance_pct")),
            price_tolerance=float(cfg.get("invoice.price_mismatch_pct"))))
    return out


async def _duplicate_checks(ctx: SiteContext, invoice: Invoice) -> list[Issue]:
    """FR-INV-12: same supplier + normalised number, or same supplier + date + total within 0.5%."""
    tolerance = Decimal(str(ctx.config.get("invoice.duplicate_total_tolerance_pct")))
    others = (await ctx.session.execute(select(Invoice).where(
        Invoice.site_id == ctx.site_id, Invoice.supplier_id == invoice.supplier_id, Invoice.id != invoice.id,
        Invoice.status.not_in(("rejected", "duplicate", "failed", "not_invoice"))))).scalars().all()
    out: list[Issue] = []
    for other in others:
        same_number = invoice.normalised_number and other.normalised_number == invoice.normalised_number
        same_amount = (invoice.invoice_date is not None and other.invoice_date == invoice.invoice_date
                       and invoice.total_minor and abs(other.total_minor - invoice.total_minor)
                       <= tolerance * abs(invoice.total_minor))
        if same_number or same_amount:
            why = "the same invoice number" if same_number else "the same date and total"
            out.append(Issue("possible_duplicate", "critical",
                             f"Possible duplicate of invoice {other.number or '(no number)'} "
                             f"({other.invoice_date or 'no date'}, {other.total_minor / 100:.2f}, {other.status}) - {why}.",
                             {"other_invoice_id": str(other.id),
                              "other_document_id": str(other.document_id) if other.document_id else None,
                              "other_number": other.number, "other_status": other.status,
                              "other_total_minor": other.total_minor, "rule": "number" if same_number else "date_total"},
                             subject=f"duplicate:{other.id}"))
    return out


async def save_exceptions(session: AsyncSession, doc: InvoiceDocument, invoice: Invoice | None, issues: list[Issue],
                          line_ids: dict[int, uuid.UUID]) -> None:
    """Replace open exceptions with the new findings; keep acceptances whose fingerprint still applies."""
    existing = {e.fingerprint: e for e in (await session.execute(select(InvoiceException).where(
        InvoiceException.document_id == doc.id, InvoiceException.status != "resolved"))).scalars()}
    seen = set()
    for issue in issues:
        fp = issue.fingerprint
        if fp in seen:
            continue
        seen.add(fp)
        policy = POLICY[issue.code]
        current = existing.get(fp)
        if current is not None:
            current.severity, current.message, current.facts = issue.severity, issue.message[:600], _json(issue.facts)
            current.blocks_approval = issue.blocks
            current.requires_role = policy.requires_role
            current.line_id = line_ids.get(issue.line_no) if issue.line_no else None
            continue
        session.add(InvoiceException(
            organisation_id=doc.organisation_id, site_id=doc.site_id, document_id=doc.id,
            invoice_id=invoice.id if invoice else None, line_id=line_ids.get(issue.line_no) if issue.line_no else None,
            code=issue.code, severity=issue.severity, blocks_approval=issue.blocks, requires_role=policy.requires_role,
            message=issue.message[:600], facts=_json(issue.facts), fingerprint=fp, status="open"))
    for fp, exc in existing.items():
        if fp not in seen:
            exc.status = "resolved"
    await session.flush()


def _json(facts: dict[str, Any]) -> dict[str, Any]:
    from app.core.audit import to_jsonable

    return to_jsonable(facts)


async def open_blockers(session: AsyncSession, doc_id: uuid.UUID) -> list[InvoiceException]:
    return list((await session.execute(select(InvoiceException).where(
        InvoiceException.document_id == doc_id, InvoiceException.status == "open",
        InvoiceException.blocks_approval.is_(True)))).scalars())


async def settle_state(ctx: SiteContext, doc: InvoiceDocument, invoice: Invoice, *, actor: str, reason: str) -> None:
    """needs_review while anything blocks approval, otherwise ready_for_approval.

    Editing an approved invoice voids the approval (FR-INV-15)."""
    if doc.state == "validating":
        await transition(ctx.session, doc, "matching", actor=actor, reason="Validated; matching supplier and lines.",
                         invoice=invoice)
    blockers = await open_blockers(ctx.session, doc.id)
    target = "needs_review" if blockers else "ready_for_approval"
    if doc.state == "approved":
        invoice.approved_by = invoice.approved_role = invoice.approved_at = None
        reason = f"{reason} The approval was voided."
    if doc.state != target or doc.state in ("needs_review", "ready_for_approval"):
        summary = ", ".join(sorted({b.code for b in blockers})) if blockers else "no blocking exceptions"
        await transition(ctx.session, doc, target, actor=actor, reason=f"{reason} ({summary})", invoice=invoice)


async def store_extraction(ctx: SiteContext, doc: InvoiceDocument, ex: InvoiceExtraction | None, *,
                           actor: str) -> Invoice:
    """Persist the immutable AI output (first one wins), build the invoice and evaluate it."""
    if doc.extraction is None:
        assert ex is not None
        doc.extraction = ex.model_dump(mode="json")
    await ctx.session.execute(delete(Invoice).where(Invoice.document_id == doc.id))
    invoice, lines = build_invoice(ctx, doc, InvoiceExtraction.model_validate(doc.extraction))
    ctx.session.add(invoice)
    await ctx.session.flush()
    ctx.session.add_all(lines)
    await ctx.session.flush()
    await transition(ctx.session, doc, "validating", actor=actor, reason=f"Extracted {len(lines)} line(s).", invoice=invoice)
    await evaluate(ctx, doc, invoice, actor=actor, reason="Validation and matching complete.")
    return invoice


# ---------------------------------------------------------------------------------------------------
# Posting (FR-INV-16)
# ---------------------------------------------------------------------------------------------------
async def post_invoice(ctx: SiteContext, doc: InvoiceDocument, invoice: Invoice, *, actor: str) -> dict:
    """Receipt movements (base-unit quantity and cost), price observations, GRN/PO links. Idempotent."""
    from app.domain.inventory.services import ReceiptLine, post_receipts
    from app.domain.purchasing.models import PriceObservation

    if invoice.posted_at is not None:
        return {"posted": False, "reason": "already posted"}
    lines = list((await ctx.session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id))).scalars())
    stock = [line for line in lines if not line.non_stock and line.ingredient_id and line.qty_base and line.qty_base > 0
             and line.price_per_base_minor is not None]
    business_date = invoice.delivery_date or invoice.invoice_date or await ctx.today()
    received_at = datetime.combine(business_date, time(7, 30), tzinfo=ctx.tz)
    if invoice.goods_receipt_id:
        gr = await ctx.session.get(GoodsReceipt, invoice.goods_receipt_id)
        if gr is not None:
            received_at, business_date = gr.received_at, gr.business_date
            gr.invoice_id, gr.invoice_number = invoice.id, invoice.number
    receipts = await post_receipts(ctx, lines=[ReceiptLine(line.ingredient_id, Decimal(line.qty_base or 0),  # type: ignore[arg-type]
                                                           Decimal(line.price_per_base_minor or 0)) for line in stock],
                                   at=received_at, business_date=business_date, ref_type="invoice", ref_id=str(invoice.id))
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    products = {p.id: p for p in (await supplier_products(ctx.session, ctx.site_id, invoice.supplier_id))} \
        if invoice.supplier_id else {}
    observations = 0
    for line in stock:
        product = products.get(line.supplier_product_id)  # type: ignore[arg-type]
        if product is None:
            continue
        result = await ctx.session.execute(pg_insert(PriceObservation).values(
            id=uuid.uuid4(), organisation_id=ctx.organisation_id, site_id=ctx.site_id, supplier_id=invoice.supplier_id,
            supplier_product_id=product.id, ingredient_id=product.ingredient_id, observed_on=business_date,
            unit_price_minor=int((Decimal(line.price_per_base_minor or 0) * product.base_qty_per_unit)
                                 .to_integral_value()),
            price_per_base_minor=line.price_per_base_minor, source="invoice", source_ref=str(invoice.id),
        ).on_conflict_do_nothing(index_elements=["site_id", "supplier_product_id", "source", "source_ref"]))
        observations += getattr(result, "rowcount", 0) or 0
    invoice.posted_at = datetime.now(UTC)
    await transition(ctx.session, doc, "posted", actor=actor,
                     reason=f"Posted {receipts} receipt movement(s) and {observations} price observation(s).",
                     invoice=invoice)
    if invoice.purchase_order_id:
        await ctx.session.execute(update(PurchaseOrder).where(
            PurchaseOrder.id == invoice.purchase_order_id, PurchaseOrder.status.in_(("sent", "committed"))
        ).values(status="received"))
    return {"posted": True, "receipts": receipts, "price_observations": observations,
            "non_stock_lines": sum(1 for line in lines if line.non_stock)}


async def supplier_name(session: AsyncSession, supplier_id: uuid.UUID | None) -> str | None:
    if supplier_id is None:
        return None
    return (await session.execute(select(Supplier.name).where(Supplier.id == supplier_id))).scalar()


_ = (timedelta, PortError)
