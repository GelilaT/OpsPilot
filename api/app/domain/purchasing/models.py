"""Purchasing context: suppliers, supplier products, price history (FR-PRC-01), purchase orders and goods
received (three-way match inputs), learned line aliases (FR-INV-09)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.tenancy.scoping import OrgScoped, SiteScoped

PO_STATUSES = ("draft", "pending_approval", "committed", "sent", "part_received", "received", "cancelled")
PRICE_SOURCES = ("invoice", "price_list", "purchase_order", "seed")


class Supplier(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "supplier"
    __table_args__ = (
        Index("ix_supplier_name_trgm", "normalised_name", postgresql_using="gin",
              postgresql_ops={"normalised_name": "gin_trgm_ops"}),
        Index("ix_supplier_vat", "organisation_id", "vat_number"),
    )

    name: Mapped[str] = mapped_column(String(200))
    normalised_name: Mapped[str] = mapped_column(String(200))
    vat_number: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(String(400))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    lead_time_days: Mapped[int] = mapped_column(default=1)
    delivery_weekdays: Mapped[list[int]] = mapped_column(JSONB, default=list)  # 0 = Monday
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SupplierAlias(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "supplier_alias"
    __table_args__ = (
        Index("uq_supplier_alias", "organisation_id", "alias", unique=True),
        Index("ix_supplier_alias_trgm", "alias", postgresql_using="gin", postgresql_ops={"alias": "gin_trgm_ops"}),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String(200))


class SupplierProduct(UUIDPk, Timestamps, OrgScoped, Base):
    """What a supplier sells: one purchase unit = `base_qty_per_unit` of the ingredient's base unit."""

    __tablename__ = "supplier_product"
    __table_args__ = (
        Index("uq_supplier_product_sku", "supplier_id", "sku", unique=True),
        CheckConstraint("base_qty_per_unit > 0", name="base_qty_positive"),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier.id", ondelete="CASCADE"))
    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredient.id", ondelete="RESTRICT"))
    sku: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    purchase_unit: Mapped[str] = mapped_column(String(30))
    pack_size: Mapped[str | None] = mapped_column(String(60))
    base_qty_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    moq_units: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal(1))
    contract_price_minor: Mapped[int | None]
    contract_valid_until: Mapped[date | None] = mapped_column(Date)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal(0))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LineAlias(UUIDPk, Timestamps, OrgScoped, Base):
    """A manager-confirmed mapping from invoice line text to a supplier product (FR-INV-09)."""

    __tablename__ = "line_alias"
    __table_args__ = (Index("uq_line_alias", "supplier_id", "normalised_text", unique=True),)

    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier.id", ondelete="CASCADE"))
    normalised_text: Mapped[str] = mapped_column(String(300))
    supplier_product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier_product.id", ondelete="CASCADE"))
    confirmed_by: Mapped[str] = mapped_column(String(120))


class PriceObservation(UUIDPk, SiteScoped, Base):
    """Append-only price history normalised per base unit (FR-PRC-01)."""

    __tablename__ = "price_observation"
    __table_args__ = (
        CheckConstraint(f"source IN {PRICE_SOURCES}", name="source_valid"),
        Index("ix_price_obs_ingredient_day", "site_id", "ingredient_id", "observed_on"),
        Index("ix_price_obs_product_day", "supplier_product_id", "observed_on"),
        Index("uq_price_obs_source", "site_id", "supplier_product_id", "source", "source_ref", unique=True),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier.id", ondelete="CASCADE"))
    supplier_product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier_product.id", ondelete="CASCADE"))
    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredient.id", ondelete="CASCADE"))
    observed_on: Mapped[date] = mapped_column(Date)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)  # per purchase unit
    price_per_base_minor: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    source: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[str] = mapped_column(String(80))


class PurchaseOrder(UUIDPk, Timestamps, SiteScoped, Base):
    __tablename__ = "purchase_order"
    __table_args__ = (
        CheckConstraint(f"status IN {PO_STATUSES}", name="status_valid"),
        Index("uq_purchase_order_number", "organisation_id", "number", unique=True),
        Index("ix_purchase_order_supplier_delivery", "site_id", "supplier_id", "expected_delivery_date"),
    )

    number: Mapped[str] = mapped_column(String(40))
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    order_date: Mapped[date] = mapped_column(Date)
    expected_delivery_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    created_by: Mapped[str] = mapped_column(String(120))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recommendation_id: Mapped[uuid.UUID | None]
    notes: Mapped[str | None] = mapped_column(String(1000))
    version: Mapped[int] = mapped_column(default=1)


class PurchaseOrderLine(UUIDPk, SiteScoped, Base):
    __tablename__ = "purchase_order_line"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_order.id", ondelete="CASCADE"),
                                                         index=True)
    supplier_product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier_product.id", ondelete="RESTRICT"))
    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredient.id", ondelete="RESTRICT"))
    qty_units: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    qty_base: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)
    line_total_minor: Mapped[int] = mapped_column(BigInteger)
    reason_codes: Mapped[list[Any]] = mapped_column(JSONB, default=list)


class GoodsReceipt(UUIDPk, Timestamps, SiteScoped, Base):
    """What actually arrived (GRN), independent of what was invoiced."""

    __tablename__ = "goods_receipt"
    __table_args__ = (Index("ix_goods_receipt_po", "purchase_order_id"),)

    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_order.id", ondelete="SET NULL"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier.id", ondelete="RESTRICT"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    business_date: Mapped[date] = mapped_column(Date)
    received_by: Mapped[str] = mapped_column(String(120))
    delivery_note_ref: Mapped[str | None] = mapped_column(String(80))
    invoice_number: Mapped[str | None] = mapped_column(String(80))
    invoice_id: Mapped[uuid.UUID | None]  # linked when the invoice is posted (FR-INV-16)


class GoodsReceiptLine(UUIDPk, SiteScoped, Base):
    __tablename__ = "goods_receipt_line"

    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goods_receipt.id", ondelete="CASCADE"),
                                                        index=True)
    purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_order_line.id", ondelete="SET NULL"))
    supplier_product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier_product.id", ondelete="RESTRICT"))
    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredient.id", ondelete="RESTRICT"))
    qty_units: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    qty_base: Mapped[Decimal] = mapped_column(Numeric(18, 4))
