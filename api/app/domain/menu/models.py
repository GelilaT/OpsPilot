"""Menu context: menu items, site prices and versioned recipes (FR-MNU-01)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.tenancy.scoping import OrgScoped, SiteScoped


class MenuItem(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "menu_item"
    __table_args__ = (Index("uq_menu_item_code", "organisation_id", "code", unique=True),)

    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MenuItemPrice(UUIDPk, Timestamps, SiteScoped, Base):
    """Price history per site (gross, VAT inclusive). The latest open row is the current price."""

    __tablename__ = "menu_item_price"
    __table_args__ = (
        Index("ix_menu_item_price", "site_id", "menu_item_id", "effective_from"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="dates_ordered"),
    )

    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_item.id", ondelete="CASCADE"))
    price_minor: Mapped[int] = mapped_column(BigInteger)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)


class Recipe(UUIDPk, Timestamps, OrgScoped, Base):
    """Versioned bill of materials; versions do not overlap (effective_to = next version's start)."""

    __tablename__ = "recipe"
    __table_args__ = (
        Index("uq_recipe_version", "menu_item_id", "version", unique=True),
        Index("uq_recipe_open_version", "menu_item_id", unique=True, postgresql_where=text("effective_to IS NULL")),
        CheckConstraint("yield_portions >= 1", name="yield_positive"),
    )

    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_item.id", ondelete="CASCADE"))
    version: Mapped[int]
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    yield_portions: Mapped[int] = mapped_column(default=1)


class RecipeLine(UUIDPk, OrgScoped, Base):
    """Quantity in any unit plus waste factor. `qty_base_per_portion` is derived on write:
    quantity converted to the ingredient's base unit x (1 + waste_factor) / recipe.yield_portions."""

    __tablename__ = "recipe_line"
    __table_args__ = (Index("ix_recipe_line_recipe", "recipe_id"),)

    recipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"))
    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredient.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit: Mapped[str] = mapped_column(String(30))
    waste_factor: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal(0))
    qty_base_per_portion: Mapped[Decimal] = mapped_column(Numeric(18, 6))
