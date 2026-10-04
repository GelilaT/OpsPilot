"""Tenant hierarchy: Organisation -> Site -> Membership (FR-TEN-01, FR-TEN-03).

Users are owned by Better Auth (table "user"); OpsPilot stores which organisation a user belongs to
(`organisation_user`, one organisation per user) and their role per site (`membership`; a null site
means every site of the organisation).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.tenancy.scoping import OrgScoped, SiteScoped

ROLE_VALUES = ("owner", "general_manager", "head_chef", "shift_manager")


class Organisation(UUIDPk, Timestamps, Base):
    __tablename__ = "organisation"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    default_currency: Mapped[str] = mapped_column(String(3), default="GBP")
    default_timezone: Mapped[str] = mapped_column(String(64), default="Europe/London")


class Site(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "site"

    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3))
    vat_scheme: Mapped[str] = mapped_column(String(40), default="uk_standard")
    region: Mapped[str] = mapped_column(String(40), default="england-and-wales")
    address: Mapped[str | None] = mapped_column(String(400))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    covers: Mapped[int | None]


class OrganisationUser(Timestamps, OrgScoped, Base):
    """A Better Auth user's single organisation (FR-TEN-03)."""

    __tablename__ = "organisation_user"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(120))  # first name + last initial (GDPR)


class Membership(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "membership"
    __table_args__ = (
        CheckConstraint(f"role IN {ROLE_VALUES}", name="role_valid"),
        Index("uq_membership_user_site", "user_id", "site_id", unique=True,
              postgresql_where=text("site_id IS NOT NULL")),
        Index("uq_membership_user_org", "user_id", unique=True, postgresql_where=text("site_id IS NULL")),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("organisation_user.user_id", ondelete="CASCADE"))
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32))


class SiteClock(SiteScoped, Base):
    """Business date of a site running on the simulator clock (FR-ING-02). Without a row (or with
    simulation disabled in configuration) the site runs on real time in its own timezone."""

    __tablename__ = "site_clock"
    __table_args__ = (Index("uq_site_clock_site", "site_id", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_date: Mapped[date] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
