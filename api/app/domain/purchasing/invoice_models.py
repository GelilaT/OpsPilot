"""Invoice intake models (SRS S4): the uploaded document and its journey (state machine), the validated
invoice and lines, exceptions with computed facts, and the AI call log."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.tenancy.scoping import SiteScoped

INTAKE_STATES = ("received", "classifying", "extracting", "validating", "matching", "needs_review",
                 "ready_for_approval", "approved", "rejected", "posted", "not_invoice", "duplicate", "failed")
DOCUMENT_TYPES = ("invoice", "credit_note", "statement", "delivery_note", "purchase_order", "receipt", "other")
EXCEPTION_CODES = ("math_error", "missing_field", "unmatched_unit", "unknown_supplier", "unmatched_line",
                   "price_increase", "contract_breach", "qty_mismatch", "price_mismatch", "possible_duplicate",
                   "low_confidence")


class InvoiceDocument(UUIDPk, Timestamps, SiteScoped, Base):
    """One uploaded file and its journey through intake. `state` changes only through transition()."""

    __tablename__ = "invoice_document"
    __table_args__ = (
        CheckConstraint(f"state IN {INTAKE_STATES}", name="state_valid"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"),
        Index("ix_invoice_document_site_state", "site_id", "state", "created_at"),
        # An exact duplicate (same site + SHA-256) is stored as its own row in state 'duplicate'.
        Index("uq_invoice_document_sha", "site_id", "sha256", unique=True,
              postgresql_where=text("duplicate_of_id IS NULL AND state <> 'failed'")),
    )

    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(400))
    preview_key: Mapped[str | None] = mapped_column(String(400))  # JPEG rendition for HEIC originals
    filename: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(60))
    size_bytes: Mapped[int] = mapped_column(Integer)
    pages: Mapped[int | None]
    source: Mapped[str] = mapped_column(String(20), default="upload")  # upload | simulate
    state: Mapped[str] = mapped_column(String(24), default="received")
    doc_type: Mapped[str | None] = mapped_column(String(24))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    multiple_documents: Mapped[bool | None] = mapped_column(Boolean)
    classification_reason: Mapped[str | None] = mapped_column(String(300))
    extraction: Mapped[dict | None] = mapped_column(JSONB)  # raw schema-valid AI output; immutable once stored
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(String(600))
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoice_document.id", ondelete="SET NULL"))
    uploaded_by: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)


class InvoiceTransition(UUIDPk, SiteScoped, Base):
    """Every state change with actor, reason and timestamp (FR-INV-13)."""

    __tablename__ = "invoice_transition"
    __table_args__ = (Index("ix_invoice_transition_doc", "document_id", "at"),)

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoice_document.id", ondelete="CASCADE"))
    from_state: Mapped[str | None] = mapped_column(String(24))
    to_state: Mapped[str] = mapped_column(String(24))
    actor: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(String(600))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invoice(UUIDPk, Timestamps, SiteScoped, Base):
    """The validated business record. Totals are recomputed from lines; AI totals kept for comparison."""

    __tablename__ = "invoice"
    __table_args__ = (
        Index("ix_invoice_supplier_number", "site_id", "supplier_id", "normalised_number"),
        Index("ix_invoice_supplier_date", "site_id", "supplier_id", "invoice_date"),
        Index("uq_invoice_document", "document_id", unique=True, postgresql_where=text("document_id IS NOT NULL")),
    )

    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoice_document.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(20), default="upload")  # upload | simulate | supplier_edi
    status: Mapped[str] = mapped_column(String(24), default="validating")
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("supplier.id", ondelete="SET NULL"))
    supplier_name: Mapped[str | None] = mapped_column(String(300))
    supplier_vat_number: Mapped[str | None] = mapped_column(String(60))
    supplier_address: Mapped[str | None] = mapped_column(String(400))
    number: Mapped[str | None] = mapped_column(String(80))
    normalised_number: Mapped[str | None] = mapped_column(String(80))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    delivery_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    po_reference: Mapped[str | None] = mapped_column(String(80))
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_order.id", ondelete="SET NULL"))
    goods_receipt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goods_receipt.id", ondelete="SET NULL"))
    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    vat_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    ai_subtotal_minor: Mapped[int | None] = mapped_column(BigInteger)
    ai_vat_minor: Mapped[int | None] = mapped_column(BigInteger)
    ai_total_minor: Mapped[int | None] = mapped_column(BigInteger)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_role: Mapped[str | None] = mapped_column(String(32))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_reason: Mapped[str | None] = mapped_column(String(600))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class InvoiceLine(UUIDPk, SiteScoped, Base):
    """A line normalised to the ingredient's base unit (qty_base) once matched."""

    __tablename__ = "invoice_line"
    __table_args__ = (Index("uq_invoice_line_no", "invoice_id", "line_no", unique=True),)

    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoice.id", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(Integer)
    raw_description: Mapped[str] = mapped_column(String(400))
    supplier_sku: Mapped[str | None] = mapped_column(String(80))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    uom: Mapped[str | None] = mapped_column(String(30))
    pack_size: Mapped[str | None] = mapped_column(String(60))
    unit_price_minor: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))  # may carry fractional pence
    line_total_minor: Mapped[int | None] = mapped_column(BigInteger)
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))  # fraction, 0.20 = 20%
    supplier_product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("supplier_product.id", ondelete="SET NULL"))
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingredient.id", ondelete="SET NULL"))
    qty_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    price_per_base_minor: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    match_method: Mapped[str | None] = mapped_column(String(20))  # sku | alias | fuzzy | suggested | manual
    match_candidates: Mapped[list[Any] | None] = mapped_column(JSONB)
    non_stock: Mapped[bool] = mapped_column(Boolean, default=False)


class InvoiceException(UUIDPk, Timestamps, SiteScoped, Base):
    """An issue found on a document or invoice, with the computed facts that explain it."""

    __tablename__ = "invoice_exception"
    __table_args__ = (
        CheckConstraint(f"code IN {EXCEPTION_CODES}", name="code_valid"),
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="severity_valid"),
        CheckConstraint("status IN ('open', 'accepted', 'resolved')", name="status_valid"),
        Index("ix_invoice_exception_doc", "document_id", "status"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoice_document.id", ondelete="CASCADE"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoice.id", ondelete="CASCADE"))
    line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoice_line.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    blocks_approval: Mapped[bool] = mapped_column(Boolean)
    requires_role: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(String(600))
    facts: Mapped[dict] = mapped_column(JSONB, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(200))  # code + subject, keeps acceptances across revalidation
    status: Mapped[str] = mapped_column(String(10), default="open")
    accepted_by: Mapped[str | None] = mapped_column(String(120))
    accepted_note: Mapped[str | None] = mapped_column(String(600))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AICall(UUIDPk, SiteScoped, Base):
    """AI call log (SRS 2.4 observability): purpose, model, latency, tokens and outcome."""

    __tablename__ = "ai_call"
    __table_args__ = (Index("ix_ai_call_site_at", "site_id", "at"),)

    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoice_document.id", ondelete="SET NULL"))
    purpose: Mapped[str] = mapped_column(String(30))  # classify | extract | narrate | embed
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(80))
    latency_ms: Mapped[int | None]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    outcome: Mapped[str] = mapped_column(String(40))  # ok | schema_error | rate_limited | transient | permanent
    detail: Mapped[str | None] = mapped_column(String(400))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
