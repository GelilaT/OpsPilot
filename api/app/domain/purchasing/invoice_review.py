"""Invoice review use cases (FR-INV-09/14/15/17): edit and revalidate, map lines (learning aliases),
accept exceptions, approve within role limits, reject and retry."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.audit import record_audit, snapshot
from app.core.errors import Conflict, Forbidden, NotFound, PreconditionFailed, Unprocessable
from app.core.jobs import enqueue, job_key
from app.core.tenancy.context import SiteContext
from app.domain.purchasing.invoice_models import Invoice, InvoiceDocument, InvoiceException, InvoiceLine
from app.domain.purchasing.invoice_pipeline import enqueue_processing, evaluate, open_blockers, transition
from app.domain.purchasing.invoice_rules import (
    EDITABLE,
    POLICY,
    ROLE_RANK,
    normalise_invoice_number,
    normalise_text,
    required_role,
    within_limit,
)
from app.domain.purchasing.models import LineAlias, Supplier, SupplierProduct


@dataclass
class LoadedInvoice:
    doc: InvoiceDocument
    invoice: Invoice | None


async def load(ctx: SiteContext, document_id: uuid.UUID, *, lock: bool = True) -> LoadedInvoice:
    q = select(InvoiceDocument).where(InvoiceDocument.id == document_id)
    doc = (await ctx.session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if doc is None:
        raise NotFound("Invoice not found.")
    invoice = (await ctx.session.execute(select(Invoice).where(Invoice.document_id == doc.id))).scalar_one_or_none()
    return LoadedInvoice(doc, invoice)


def _require_editable(li: LoadedInvoice, expected_version: int | None) -> Invoice:
    if li.invoice is None or li.doc.state not in EDITABLE:
        raise Conflict(f"An invoice in state {li.doc.state!r} cannot be edited.", code="not_editable")
    if expected_version is not None and expected_version != li.doc.version:
        raise PreconditionFailed(f"The invoice changed (version {li.doc.version}); reload and try again.",
                                 code="stale_version", extra={"current_version": li.doc.version})
    return li.invoice


HEADER_FIELDS = ("supplier_name", "supplier_vat_number", "number", "invoice_date", "delivery_date", "due_date",
                 "po_reference", "currency")
LINE_FIELDS = ("raw_description", "supplier_sku", "quantity", "uom", "pack_size", "unit_price_minor",
               "line_total_minor", "vat_rate")


async def edit_invoice(ctx: SiteContext, document_id: uuid.UUID, *, header: dict[str, Any], lines: list[dict[str, Any]],
                       supplier_id: uuid.UUID | None, expected_version: int | None) -> LoadedInvoice:
    """Edit fields/lines; the invoice is revalidated immediately (FR-INV-14) and an approval is voided."""
    li = await load(ctx, document_id)
    invoice = _require_editable(li, expected_version)
    before = snapshot(invoice)
    for key, value in header.items():
        if key not in HEADER_FIELDS:
            raise Unprocessable(f"Field {key!r} cannot be edited.", code="invalid_field")
        if key == "currency" and value:
            value = str(value).upper()
        setattr(invoice, key, value)
    if "number" in header:
        invoice.normalised_number = normalise_invoice_number(invoice.number)
    if supplier_id is not None:
        if (await ctx.session.get(Supplier, supplier_id)) is None:
            raise NotFound("Supplier not found.")
        if supplier_id != invoice.supplier_id:
            invoice.supplier_id = supplier_id
            for line in (await ctx.session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id))).scalars():
                if line.match_method != "manual":
                    line.match_method = None
    existing = {line.id: line for line in (await ctx.session.execute(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id))).scalars()}
    next_no = max((line.line_no for line in existing.values()), default=0) + 1
    for change in lines:
        line_id = change.get("id")
        if change.get("delete"):
            if line_id is None or line_id not in existing:
                raise NotFound(f"Line {line_id} not found.")
            await ctx.session.delete(existing[line_id])
            continue
        if line_id is None:
            line = InvoiceLine(id=uuid.uuid4(), organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                               invoice_id=invoice.id, line_no=next_no, raw_description=change.get("raw_description") or "")
            next_no += 1
            ctx.session.add(line)
        elif line_id in existing:
            line = existing[line_id]
        else:
            raise NotFound(f"Line {line_id} not found.")
        for key in LINE_FIELDS:
            if key in change:
                setattr(line, key, change[key])
        if {"raw_description", "supplier_sku", "uom", "pack_size"} & change.keys() and line.match_method != "manual":
            line.match_method = None
    invoice.edited = True
    invoice.version += 1
    await ctx.session.flush()
    record_audit(ctx.session, actor=ctx.actor, entity_type="invoice", entity_id=invoice.id, action="edit",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id, before=before,
                 after={"header": header, "lines": lines, "supplier_id": supplier_id})
    await evaluate(ctx, li.doc, invoice, actor=ctx.actor, reason="Edited and revalidated.")
    return li


async def match_line(ctx: SiteContext, document_id: uuid.UUID, line_id: uuid.UUID, *,
                     supplier_product_id: uuid.UUID | None, non_stock: bool) -> LoadedInvoice:
    """Confirm a mapping (creates a LineAlias so the same text matches next time) or mark non-stock."""
    li = await load(ctx, document_id)
    invoice = _require_editable(li, None)
    line = await ctx.session.get(InvoiceLine, line_id)
    if line is None or line.invoice_id != invoice.id:
        raise NotFound("Line not found.")
    if non_stock:
        line.non_stock, line.supplier_product_id, line.ingredient_id = True, None, None
        line.match_method = "manual"
    else:
        if supplier_product_id is None:
            raise Unprocessable("Choose a supplier product or mark the line non-stock.", code="product_required")
        product = await ctx.session.get(SupplierProduct, supplier_product_id)
        if product is None:
            raise NotFound("Supplier product not found.")
        if invoice.supplier_id is None:
            invoice.supplier_id = product.supplier_id
        if product.supplier_id != invoice.supplier_id:
            raise Unprocessable("That product belongs to another supplier.", code="wrong_supplier")
        line.non_stock = False
        line.supplier_product_id, line.ingredient_id = product.id, product.ingredient_id
        line.match_method, line.match_confidence = "manual", Decimal(1)
        text = normalise_text(line.raw_description)
        if text:
            await ctx.session.execute(insert(LineAlias).values(
                id=uuid.uuid4(), organisation_id=ctx.organisation_id, supplier_id=product.supplier_id,
                normalised_text=text, supplier_product_id=product.id, confirmed_by=ctx.actor,
            ).on_conflict_do_update(index_elements=["supplier_id", "normalised_text"],
                                    set_={"supplier_product_id": product.id, "confirmed_by": ctx.actor}))
    record_audit(ctx.session, actor=ctx.actor, entity_type="invoice_line", entity_id=line.id, action="match",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                 after={"supplier_product_id": supplier_product_id, "non_stock": non_stock,
                        "raw_description": line.raw_description})
    await ctx.session.flush()
    await evaluate(ctx, li.doc, invoice, actor=ctx.actor, reason=f"Line {line.line_no} mapped.")
    return li


async def accept_exception(ctx: SiteContext, document_id: uuid.UUID, exception_id: uuid.UUID, *, note: str,
                           role: str) -> LoadedInvoice:
    li = await load(ctx, document_id)
    exc = await ctx.session.get(InvoiceException, exception_id)
    if exc is None or exc.document_id != li.doc.id:
        raise NotFound("Exception not found.")
    if exc.status != "open":
        raise Conflict("This exception is not open.", code="exception_not_open")
    if not POLICY[exc.code].acceptable:
        raise Unprocessable(f"{exc.code} cannot be accepted - correct the invoice instead.", code="not_acceptable")
    needs = "general_manager" if exc.severity == "critical" or exc.requires_role else "head_chef"
    if ROLE_RANK[role] < ROLE_RANK[needs]:
        raise Forbidden(f"Accepting this exception requires {needs.replace('_', ' ')} or above.")
    exc.status, exc.accepted_by, exc.accepted_note, exc.accepted_at = "accepted", ctx.actor, note, datetime.now(UTC)
    record_audit(ctx.session, actor=ctx.actor, entity_type="invoice_exception", entity_id=exc.id, action="accept",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                 after={"code": exc.code, "note": note, "facts": exc.facts})
    await ctx.session.flush()
    if exc.code == "low_confidence" and li.doc.state == "needs_review" and li.invoice is None:
        # The reviewer confirms it is a single invoice: continue with extraction.
        await transition(ctx.session, li.doc, "extracting", actor=ctx.actor, reason=f"Confirmed as an invoice: {note}")
        await enqueue_processing(ctx.session, li.doc)
        return li
    if li.invoice is not None and li.doc.state in EDITABLE:
        await evaluate(ctx, li.doc, li.invoice, actor=ctx.actor, reason=f"{exc.code} accepted.")
    return li


async def approval_requirement(ctx: SiteContext, li: LoadedInvoice) -> tuple[str, dict[str, int | None]]:
    assert li.invoice is not None
    limits = ctx.config.get("approval.invoice_limits").model_dump()
    excs = (await ctx.session.execute(select(InvoiceException.code, InvoiceException.status, InvoiceException.requires_role)
                                      .where(InvoiceException.document_id == li.doc.id,
                                             InvoiceException.status != "resolved"))).all()
    return required_role(total_minor=li.invoice.total_minor, limits=limits,
                         exceptions=[(c, s, r or "") for c, s, r in excs]), limits


async def approve(ctx: SiteContext, document_id: uuid.UUID, *, role: str, expected_version: int | None) -> LoadedInvoice:
    """Approve within the role's limit (FR-INV-15); posting follows as a job in the same transaction."""
    li = await load(ctx, document_id)
    if li.doc.state != "ready_for_approval" or li.invoice is None:
        blockers = await open_blockers(ctx.session, li.doc.id)
        detail = f" Open: {', '.join(sorted({b.code for b in blockers}))}." if blockers else ""
        raise Conflict(f"The invoice is {li.doc.state.replace('_', ' ')} and cannot be approved.{detail}",
                       code="not_ready", extra={"state": li.doc.state, "blocking": [b.code for b in blockers]})
    if expected_version is not None and expected_version != li.doc.version:
        raise PreconditionFailed("The invoice changed; reload and try again.", code="stale_version")
    needed, limits = await approval_requirement(ctx, li)
    if ROLE_RANK[role] < ROLE_RANK[needed] or not within_limit(role, li.invoice.total_minor, limits):
        raise Forbidden(f"This invoice ({li.invoice.total_minor / 100:.2f} {li.invoice.currency}) needs approval by "
                        f"{needed.replace('_', ' ')} or above.", code="approval_limit",
                        extra={"required_role": needed, "your_role": role})
    li.invoice.approved_by, li.invoice.approved_role, li.invoice.approved_at = ctx.actor, role, datetime.now(UTC)
    await transition(ctx.session, li.doc, "approved", actor=ctx.actor, reason=f"Approved by {role.replace('_', ' ')}.",
                     invoice=li.invoice)
    await enqueue(ctx.session, "invoice.post", key=job_key("invoice.post", li.invoice.id, li.doc.version),
                  lock=f"invoice:{li.doc.id}", args={"organisation_id": str(ctx.organisation_id),
                                                     "site_id": str(ctx.site_id), "document_id": str(li.doc.id)})
    return li


async def reject(ctx: SiteContext, document_id: uuid.UUID, *, reason: str) -> LoadedInvoice:
    li = await load(ctx, document_id)
    if li.doc.state not in ("needs_review", "ready_for_approval", "approved"):
        raise Conflict(f"An invoice in state {li.doc.state!r} cannot be rejected.", code="illegal_transition")
    if li.invoice is not None:
        li.invoice.rejected_reason = reason
    await transition(ctx.session, li.doc, "rejected", actor=ctx.actor, reason=f"Rejected: {reason}", invoice=li.invoice)
    return li


async def retry(ctx: SiteContext, document_id: uuid.UUID) -> LoadedInvoice:
    """Manual retry of a failed document (FR-INV-17)."""
    li = await load(ctx, document_id)
    if li.doc.state != "failed":
        raise Conflict("Only failed documents can be retried.", code="not_failed")
    if li.doc.storage_key is None:
        raise Conflict("This file was refused at upload and cannot be retried; upload a valid file.", code="not_retryable")
    li.doc.failure_reason = None
    await transition(ctx.session, li.doc, "received", actor=ctx.actor, reason="Manual retry.")
    await enqueue_processing(ctx.session, li.doc)
    return li


_ = date
