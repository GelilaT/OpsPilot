"""Invoice intake and review API (SRS 4.4; FR-INV-01..17)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, tuple_

from app.api.deps import site_context
from app.core.errors import NotFound, PayloadTooLarge, Unprocessable
from app.core.security import Role
from app.core.settings import get_settings
from app.core.tenancy.context import SiteContext
from app.domain.inventory.models import Ingredient
from app.domain.purchasing import invoice_review as review
from app.domain.purchasing.invoice_models import (
    Invoice,
    InvoiceDocument,
    InvoiceException,
    InvoiceLine,
    InvoiceTransition,
)
from app.domain.purchasing.invoice_pipeline import MAX_BYTES, intake
from app.domain.purchasing.invoice_rules import ROLE_RANK
from app.domain.purchasing.models import PurchaseOrder, Supplier, SupplierProduct
from app.ports import IntegrationKind
from app.simulation.synthetic_invoice import build_synthetic_invoice

router = APIRouter(prefix="/invoices", tags=["invoices"])
HeadChef = Annotated[SiteContext, Depends(site_context(Role.head_chef))]


# ---------------------------------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------------------------------
class DocumentSummary(BaseModel):
    id: uuid.UUID
    filename: str
    state: str
    source: str
    doc_type: str | None
    confidence: Decimal | None
    supplier_name: str | None
    invoice_number: str | None
    invoice_date: date | None
    total_minor: int | None
    currency: str | None
    open_exceptions: list[str]
    blocking: bool
    failure_reason: str | None
    duplicate_of_id: uuid.UUID | None
    created_at: datetime
    version: int


class DocumentPage(BaseModel):
    items: list[DocumentSummary]
    counts: dict[str, int]
    next_cursor: str | None


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    line_no: int
    raw_description: str
    supplier_sku: str | None
    quantity: Decimal | None
    uom: str | None
    pack_size: str | None
    unit_price_minor: Decimal | None
    line_total_minor: int | None
    vat_rate: Decimal | None
    supplier_product_id: uuid.UUID | None
    product_name: str | None = None
    ingredient_id: uuid.UUID | None
    ingredient_name: str | None = None
    base_unit: str | None = None
    qty_base: Decimal | None
    price_per_base_minor: Decimal | None
    match_method: str | None
    match_confidence: Decimal | None
    match_candidates: list[Any] | None
    non_stock: bool


class ExceptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    severity: str
    status: str
    blocks_approval: bool
    requires_role: str | None
    message: str
    facts: dict[str, Any]
    line_id: uuid.UUID | None
    accepted_by: str | None
    accepted_note: str | None
    accepted_at: datetime | None


class TransitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_state: str | None
    to_state: str
    actor: str
    reason: str
    at: datetime


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    supplier_vat_number: str | None
    matched_supplier_name: str | None = None
    number: str | None
    invoice_date: date | None
    delivery_date: date | None
    due_date: date | None
    po_reference: str | None
    purchase_order_id: uuid.UUID | None
    purchase_order_number: str | None = None
    currency: str | None
    subtotal_minor: int
    vat_minor: int
    total_minor: int
    ai_subtotal_minor: int | None
    ai_vat_minor: int | None
    ai_total_minor: int | None
    edited: bool
    approved_by: str | None
    approved_role: str | None
    approved_at: datetime | None
    rejected_reason: str | None
    posted_at: datetime | None


class Approval(BaseModel):
    required_role: str | None
    your_role: str
    can_approve: bool
    limits: dict[str, int | None]


class DocumentDetail(BaseModel):
    document: DocumentSummary
    mime: str
    size_bytes: int
    pages: int | None
    classification_reason: str | None
    file_url: str | None
    preview_url: str | None
    invoice: InvoiceOut | None
    lines: list[LineOut]
    exceptions: list[ExceptionOut]
    transitions: list[TransitionOut]
    approval: Approval | None


class LineEdit(BaseModel):
    id: uuid.UUID | None = None
    delete: bool = False
    raw_description: str | None = None
    supplier_sku: str | None = None
    quantity: Decimal | None = None
    uom: str | None = None
    pack_size: str | None = None
    unit_price_minor: Decimal | None = None
    line_total_minor: int | None = None
    vat_rate: Decimal | None = Field(None, ge=0, le=1)


class InvoiceEdit(BaseModel):
    supplier_id: uuid.UUID | None = None
    supplier_name: str | None = None
    supplier_vat_number: str | None = None
    number: str | None = None
    invoice_date: date | None = None
    delivery_date: date | None = None
    due_date: date | None = None
    po_reference: str | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    lines: list[LineEdit] = Field(default_factory=list)


class LineMatchIn(BaseModel):
    supplier_product_id: uuid.UUID | None = None
    non_stock: bool = False


class NoteIn(BaseModel):
    note: str = Field(min_length=3, max_length=600)


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=600)


class SimulateIn(BaseModel):
    supplier_id: uuid.UUID | None = None
    price_change_pct: Decimal = Field(Decimal(0), ge=-50, le=100, description="e.g. 18 for an 18% price rise")


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------
async def _summaries(ctx: SiteContext, docs: list[InvoiceDocument]) -> list[DocumentSummary]:
    ids = [d.id for d in docs]
    rows = await ctx.session.execute(select(Invoice).where(Invoice.document_id.in_(ids)))
    invoices = {i.document_id: i for i in rows.scalars()}
    open_exc: dict[uuid.UUID, list[tuple[str, bool]]] = {}
    for e in (await ctx.session.execute(select(InvoiceException.document_id, InvoiceException.code,
                                               InvoiceException.blocks_approval)
                                        .where(InvoiceException.document_id.in_(ids), InvoiceException.status == "open"))).all():
        open_exc.setdefault(e.document_id, []).append((e.code, e.blocks_approval))
    supplier_ids = {i.supplier_id for i in invoices.values() if i.supplier_id}
    names = dict((await ctx.session.execute(select(Supplier.id, Supplier.name).where(Supplier.id.in_(supplier_ids)))).all())
    out = []
    for d in docs:
        inv = invoices.get(d.id)
        excs = open_exc.get(d.id, [])
        out.append(DocumentSummary(
            id=d.id, filename=d.filename, state=d.state, source=d.source, doc_type=d.doc_type, confidence=d.confidence,
            supplier_name=((names.get(inv.supplier_id) if inv.supplier_id else None) or inv.supplier_name) if inv else None,
            invoice_number=inv.number if inv else None, invoice_date=inv.invoice_date if inv else None,
            total_minor=inv.total_minor if inv else None, currency=inv.currency if inv else None,
            open_exceptions=sorted({c for c, _ in excs}), blocking=any(b for _, b in excs),
            failure_reason=d.failure_reason, duplicate_of_id=d.duplicate_of_id, created_at=d.created_at, version=d.version))
    return out


async def _detail(ctx: SiteContext, document_id: uuid.UUID) -> DocumentDetail:
    doc = (await ctx.session.execute(select(InvoiceDocument).where(InvoiceDocument.id == document_id))).scalar_one_or_none()
    if doc is None:
        raise NotFound("Invoice not found.")
    invoice = (await ctx.session.execute(select(Invoice).where(Invoice.document_id == doc.id))).scalar_one_or_none()
    lines: list[LineOut] = []
    approval = None
    invoice_out = None
    if invoice is not None:
        rows = (await ctx.session.execute(
            select(InvoiceLine, SupplierProduct.name, Ingredient.name, Ingredient.base_unit)
            .outerjoin(SupplierProduct, SupplierProduct.id == InvoiceLine.supplier_product_id)
            .outerjoin(Ingredient, Ingredient.id == InvoiceLine.ingredient_id)
            .where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.line_no))).all()
        for line, pname, iname, base in rows:
            out = LineOut.model_validate(line)
            out.product_name, out.ingredient_name, out.base_unit = pname, iname, base
            lines.append(out)
        invoice_out = InvoiceOut.model_validate(invoice)
        if invoice.supplier_id:
            invoice_out.matched_supplier_name = (await ctx.session.execute(
                select(Supplier.name).where(Supplier.id == invoice.supplier_id))).scalar()
        if invoice.purchase_order_id:
            invoice_out.purchase_order_number = (await ctx.session.execute(
                select(PurchaseOrder.number).where(PurchaseOrder.id == invoice.purchase_order_id))).scalar()
        role = getattr(ctx, "role", Role.head_chef).value
        needed, limits = await review.approval_requirement(ctx, review.LoadedInvoice(doc, invoice))
        approval = Approval(required_role=needed, your_role=role, limits=limits,
                            can_approve=doc.state == "ready_for_approval" and ROLE_RANK[role] >= ROLE_RANK[needed]
                            and review.within_limit(role, invoice.total_minor, limits))
    exceptions = [ExceptionOut.model_validate(e) for e in (await ctx.session.execute(
        select(InvoiceException).where(InvoiceException.document_id == doc.id, InvoiceException.status != "resolved")
        .order_by(InvoiceException.blocks_approval.desc(), InvoiceException.created_at))).scalars()]
    transitions = [TransitionOut.model_validate(t) for t in (await ctx.session.execute(
        select(InvoiceTransition).where(InvoiceTransition.document_id == doc.id).order_by(InvoiceTransition.at))).scalars()]
    storage = await ctx.adapter(IntegrationKind.storage)
    file_url = await storage.signed_url(doc.storage_key, ttl_seconds=600, content_type=doc.mime) if doc.storage_key else None
    preview_url = (await storage.signed_url(doc.preview_key, ttl_seconds=600, content_type="image/jpeg")
                   if doc.preview_key else None)
    return DocumentDetail(document=(await _summaries(ctx, [doc]))[0], mime=doc.mime, size_bytes=doc.size_bytes,
                          pages=doc.pages, classification_reason=doc.classification_reason, file_url=file_url,
                          preview_url=preview_url, invoice=invoice_out, lines=lines, exceptions=exceptions,
                          transitions=transitions, approval=approval)


def _fixtures_dir() -> Path:
    fixtures = Path(get_settings().ai_fixtures_dir)
    return fixtures if fixtures.is_absolute() else Path(__file__).resolve().parents[3] / fixtures


def _if_match(if_match: str | None) -> int | None:
    if not if_match:
        return None
    try:
        return int(if_match.strip('W/"'))
    except ValueError as exc:
        raise Unprocessable("If-Match must be the invoice version number.", code="invalid_if_match") from exc


# ---------------------------------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------------------------------
@router.post("", response_model=DocumentDetail, status_code=status.HTTP_202_ACCEPTED)
async def upload(ctx: HeadChef, file: Annotated[UploadFile, File(description="PDF, JPEG, PNG, WebP or HEIC")]):
    """Upload a supplier invoice. Acknowledged immediately (202); poll GET /invoices/{id} for its state."""
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise PayloadTooLarge("The file is larger than 20 MB.")
    doc = await intake(ctx, filename=file.filename or "upload", content=content, actor=ctx.actor)
    await ctx.session.flush()
    return await _detail(ctx, doc.id)


@router.post("/simulate", response_model=DocumentDetail, status_code=status.HTTP_202_ACCEPTED)
async def simulate(ctx: HeadChef, body: SimulateIn):
    """Generate a synthetic supplier invoice from this site's catalogue and process it like an upload."""
    fixtures = _fixtures_dir()
    synthetic = await build_synthetic_invoice(
        ctx.session, site_id=ctx.site_id, site_name=ctx.site.name, site_address=ctx.site.address or "",
        currency=ctx.currency, today=await ctx.today(), supplier_id=body.supplier_id,
        price_change_pct=body.price_change_pct / 100, fixtures_dir=fixtures)
    doc = await intake(ctx, filename=synthetic.filename, content=synthetic.content, actor=ctx.actor, source="simulate")
    await ctx.session.flush()
    return await _detail(ctx, doc.id)


@router.get("", response_model=DocumentPage)
async def list_invoices(ctx: HeadChef, state: str | None = None, supplier_id: uuid.UUID | None = None,
                        exception: str | None = None, cursor: str | None = None,
                        limit: int = Query(50, ge=1, le=200)):
    q = select(InvoiceDocument)
    if state:
        q = q.where(InvoiceDocument.state.in_(state.split(",")))
    if supplier_id:
        q = q.where(InvoiceDocument.id.in_(select(Invoice.document_id).where(Invoice.supplier_id == supplier_id)))
    if exception:
        q = q.where(InvoiceDocument.id.in_(select(InvoiceException.document_id).where(
            InvoiceException.code == exception, InvoiceException.status == "open")))
    if cursor:
        try:
            created, _, last_id = cursor.partition("|")
            q = q.where(tuple_(InvoiceDocument.created_at, InvoiceDocument.id)
                        < tuple_(datetime.fromisoformat(created), uuid.UUID(last_id)))
        except ValueError as exc:
            raise Unprocessable("Invalid cursor.", code="invalid_cursor") from exc
    docs = list((await ctx.session.execute(q.order_by(InvoiceDocument.created_at.desc(), InvoiceDocument.id.desc())
                                           .limit(limit + 1))).scalars())
    more = len(docs) > limit
    docs = docs[:limit]
    counts = dict((await ctx.session.execute(select(InvoiceDocument.state, func.count()).group_by(InvoiceDocument.state))).all())
    return DocumentPage(items=await _summaries(ctx, docs), counts=counts,
                        next_cursor=f"{docs[-1].created_at.isoformat()}|{docs[-1].id}" if more and docs else None)


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_invoice(document_id: uuid.UUID, ctx: HeadChef):
    """Document, extracted fields, lines with match status and price facts, exceptions and history."""
    return await _detail(ctx, document_id)


@router.patch("/{document_id}", response_model=DocumentDetail)
async def edit_invoice(document_id: uuid.UUID, body: InvoiceEdit, ctx: HeadChef,
                       if_match: Annotated[str | None, Header()] = None):
    """Edit fields or lines; revalidated immediately. Editing an approved invoice voids the approval."""
    header = body.model_dump(exclude_unset=True, exclude={"lines", "supplier_id"})
    lines = [line.model_dump(exclude_unset=True) for line in body.lines]
    await review.edit_invoice(ctx, document_id, header=header, lines=lines, supplier_id=body.supplier_id,
                              expected_version=_if_match(if_match))
    return await _detail(ctx, document_id)


@router.post("/{document_id}/lines/{line_id}/match", response_model=DocumentDetail)
async def match_line(document_id: uuid.UUID, line_id: uuid.UUID, body: LineMatchIn, ctx: HeadChef):
    """Confirm a line's product (learned as a LineAlias) or mark it non-stock."""
    await review.match_line(ctx, document_id, line_id, supplier_product_id=body.supplier_product_id,
                            non_stock=body.non_stock)
    return await _detail(ctx, document_id)


@router.post("/{document_id}/exceptions/{exception_id}/accept", response_model=DocumentDetail)
async def accept_exception(document_id: uuid.UUID, exception_id: uuid.UUID, body: NoteIn, ctx: HeadChef):
    """Accept an exception with a note (critical exceptions need a General Manager or Owner)."""
    await review.accept_exception(ctx, document_id, exception_id, note=body.note, role=ctx.role.value)  # type: ignore[attr-defined]
    return await _detail(ctx, document_id)


@router.post("/{document_id}/approve", response_model=DocumentDetail)
async def approve(document_id: uuid.UUID, ctx: HeadChef, if_match: Annotated[str | None, Header()] = None):
    """Approve within your role's limit; the invoice is then posted to stock and price history."""
    await review.approve(ctx, document_id, role=ctx.role.value, expected_version=_if_match(if_match))  # type: ignore[attr-defined]
    return await _detail(ctx, document_id)


@router.post("/{document_id}/reject", response_model=DocumentDetail)
async def reject(document_id: uuid.UUID, body: RejectIn, ctx: HeadChef):
    await review.reject(ctx, document_id, reason=body.reason)
    return await _detail(ctx, document_id)


@router.post("/{document_id}/retry", response_model=DocumentDetail, status_code=status.HTTP_202_ACCEPTED)
async def retry(document_id: uuid.UUID, ctx: HeadChef):
    """Retry a failed document (after an AI or storage outage)."""
    await review.retry(ctx, document_id)
    return await _detail(ctx, document_id)
