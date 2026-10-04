"""Sales & labour context: POS orders, shifts, cash-ups (FR-ING-01/04/06) and external drivers
(weather, bank holidays) used by forecasting and investigations."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.tenancy.scoping import SiteScoped


class SalesOrder(UUIDPk, SiteScoped, Base):
    __tablename__ = "sales_order"
    __table_args__ = (
        Index("uq_sales_order_external", "site_id", "external_order_id", unique=True),  # FR-ING-03 idempotency
        Index("ix_sales_order_site_date", "site_id", "business_date"),
    )

    external_order_id: Mapped[str] = mapped_column(String(80))
    business_date: Mapped[date] = mapped_column(Date)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    daypart: Mapped[str] = mapped_column(String(16))
    covers: Mapped[int]
    channel: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3))
    gross_minor: Mapped[int] = mapped_column(BigInteger)  # before discounts, VAT inclusive
    discount_minor: Mapped[int] = mapped_column(BigInteger)
    void_minor: Mapped[int] = mapped_column(BigInteger)
    net_minor: Mapped[int] = mapped_column(BigInteger)  # paid, VAT inclusive
    vat_minor: Mapped[int] = mapped_column(BigInteger)
    revenue_ex_vat_minor: Mapped[int] = mapped_column(BigInteger)
    discount_reason: Mapped[str | None] = mapped_column(String(60))


class SalesOrderLine(UUIDPk, SiteScoped, Base):
    __tablename__ = "sales_order_line"
    __table_args__ = (
        Index("ix_sales_line_order", "order_id"),
        Index("ix_sales_line_site_date_item", "site_id", "business_date", "menu_item_id"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales_order.id", ondelete="CASCADE"))
    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_item.id", ondelete="RESTRICT"))
    business_date: Mapped[date] = mapped_column(Date)
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    daypart: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))  # sold (net of voids)
    void_quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal(0))
    void_reason: Mapped[str | None] = mapped_column(String(60))
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    discount_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    net_minor: Mapped[int] = mapped_column(BigInteger)  # VAT inclusive after discount
    revenue_ex_vat_minor: Mapped[int] = mapped_column(BigInteger)


class Shift(UUIDPk, SiteScoped, Base):
    __tablename__ = "shift"
    __table_args__ = (
        Index("uq_shift_external", "site_id", "external_shift_id", unique=True),
        Index("ix_shift_site_date", "site_id", "business_date"),
    )

    external_shift_id: Mapped[str] = mapped_column(String(80))
    business_date: Mapped[date] = mapped_column(Date)
    staff_ref: Mapped[str] = mapped_column(String(80))
    staff_display_name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(40))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hours: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    hourly_rate_minor: Mapped[int] = mapped_column(BigInteger)
    cost_minor: Mapped[int] = mapped_column(BigInteger)


class CashUp(UUIDPk, SiteScoped, Base):
    __tablename__ = "cash_up"
    __table_args__ = (Index("uq_cash_up_day", "site_id", "business_date", unique=True),)

    business_date: Mapped[date] = mapped_column(Date)
    expected_cash_minor: Mapped[int] = mapped_column(BigInteger)
    counted_cash_minor: Mapped[int] = mapped_column(BigInteger)
    card_total_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    variance_minor: Mapped[int] = mapped_column(BigInteger)


class WeatherDay(UUIDPk, Timestamps, SiteScoped, Base):
    __tablename__ = "weather_day"
    __table_args__ = (Index("uq_weather_day", "site_id", "day", unique=True),)

    day: Mapped[date] = mapped_column(Date)
    temp_max_c: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    temp_min_c: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    precipitation_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    source: Mapped[str] = mapped_column(String(20))


class BankHoliday(UUIDPk, Base):
    """Shared reference data (not tenant-owned): public holidays per region, cached from gov.uk."""

    __tablename__ = "bank_holiday"
    __table_args__ = (Index("uq_bank_holiday", "region", "day", unique=True),)

    region: Mapped[str] = mapped_column(String(40))
    day: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(120))
