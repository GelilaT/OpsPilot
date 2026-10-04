"""Inventory context: ingredient catalogue (FR-STK-01), append-only stock ledger (FR-STK-02), counts and
waste (FR-STK-04/05)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.tenancy.scoping import OrgScoped, SiteScoped

BASE_UNITS = ("g", "ml", "each")
MOVEMENT_TYPES = ("opening", "receipt", "theoretical_consumption", "waste", "count_adjustment", "transfer")
WASTE_REASONS = ("spoilage", "prep", "over_production", "returned", "staff_meal")

QTY = Numeric(18, 4)
UNIT_COST = Numeric(18, 6)  # minor units per base unit, e.g. 0.67 pence per gram


class Ingredient(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "ingredient"
    __table_args__ = (
        CheckConstraint(f"base_unit IN {BASE_UNITS}", name="base_unit_valid"),
        Index("uq_ingredient_org_code", "organisation_id", "code", unique=True),
    )

    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60))
    base_unit: Mapped[str] = mapped_column(String(8))
    shelf_life_days: Mapped[int | None]
    storage_area: Mapped[str] = mapped_column(String(40), default="dry_store")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class UnitConversion(UUIDPk, OrgScoped, Base):
    """Ingredient-specific (or organisation-wide when ingredient_id is null) unit -> base factor."""

    __tablename__ = "unit_conversion"
    __table_args__ = (
        Index("uq_unit_conversion", "organisation_id", "ingredient_id", "unit", unique=True,
              postgresql_nulls_not_distinct=True),
        CheckConstraint("factor_to_base > 0", name="factor_positive"),
    )

    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingredient.id", ondelete="CASCADE"))
    unit: Mapped[str] = mapped_column(String(30))
    factor_to_base: Mapped[Decimal] = mapped_column(Numeric(18, 6))


class SiteIngredient(UUIDPk, Timestamps, SiteScoped, Base):
    """Per-site stocking settings: par level and default supplier product (changed by executors)."""

    __tablename__ = "site_ingredient"
    __table_args__ = (Index("uq_site_ingredient", "site_id", "ingredient_id", unique=True),)

    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredient.id", ondelete="CASCADE"))
    par_level_base: Mapped[Decimal] = mapped_column(QTY, default=Decimal(0))
    default_supplier_product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("supplier_product.id", ondelete="SET NULL"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(default=1)


class StockMovement(SiteScoped, Base):
    """Immutable ledger row. On-hand is always derived (sum of qty_base), never stored (FR-STK-02).

    `unit_cost_minor` is the weighted average cost per base unit in effect after this movement
    (FR-STK-09); `cost_minor` is the signed value of the movement at that cost.
    """

    __tablename__ = "stock_movement"
    __table_args__ = (
        CheckConstraint(f"type IN {MOVEMENT_TYPES}", name="type_valid"),
        Index("uq_stock_movement_ref", "site_id", "ingredient_id", "type", "ref_type", "ref_id", unique=True),
        Index("ix_stock_movement_site_ingredient_at", "site_id", "ingredient_id", "at"),
        Index("ix_stock_movement_site_date", "site_id", "business_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredient.id", ondelete="RESTRICT"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    business_date: Mapped[date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(30))
    qty_base: Mapped[Decimal] = mapped_column(QTY)
    unit_cost_minor: Mapped[Decimal] = mapped_column(UNIT_COST)
    cost_minor: Mapped[int] = mapped_column(BigInteger)
    ref_type: Mapped[str] = mapped_column(String(40))
    ref_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockCount(UUIDPk, Timestamps, SiteScoped, Base):
    __tablename__ = "stock_count"

    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    business_date: Mapped[date] = mapped_column(Date)
    storage_area: Mapped[str | None] = mapped_column(String(40))  # null = full count
    status: Mapped[str] = mapped_column(String(16), default="posted")
    counted_by: Mapped[str] = mapped_column(String(120))


class StockCountLine(UUIDPk, SiteScoped, Base):
    __tablename__ = "stock_count_line"
    __table_args__ = (Index("uq_stock_count_line", "count_id", "ingredient_id", unique=True),)

    count_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_count.id", ondelete="CASCADE"))
    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredient.id", ondelete="RESTRICT"))
    counted_qty_base: Mapped[Decimal] = mapped_column(QTY)
    ledger_qty_base: Mapped[Decimal] = mapped_column(QTY)
    adjustment_qty_base: Mapped[Decimal] = mapped_column(QTY)


class WasteEntry(UUIDPk, Timestamps, SiteScoped, Base):
    __tablename__ = "waste_entry"
    __table_args__ = (CheckConstraint(f"reason IN {WASTE_REASONS}", name="reason_valid"),)

    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredient.id", ondelete="RESTRICT"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    business_date: Mapped[date] = mapped_column(Date)
    qty_base: Mapped[Decimal] = mapped_column(QTY)
    reason: Mapped[str] = mapped_column(String(20))
    cost_minor: Mapped[int] = mapped_column(BigInteger)
    recorded_by: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(400))
