"""Detection and investigation persistence (FR-ANO-01, FR-RCA-01)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.tenancy.scoping import SiteScoped

ANOMALY_STATUSES = ("open", "investigating", "dismissed", "closed")
SEVERITIES = ("info", "warning", "critical")
INVESTIGATION_STATUSES = ("complete", "failed")


class ItemCostSnapshot(UUIDPk, SiteScoped, Base):
    """Daily menu item costing snapshot (FR-MNU-02)."""

    __tablename__ = "item_cost_snapshot"
    __table_args__ = (
        UniqueConstraint("site_id", "menu_item_id", "business_date", name="uq_item_cost_snapshot_day"),
        Index("ix_item_cost_snapshot_site_day", "site_id", "business_date"),
    )

    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_item.id", ondelete="CASCADE"))
    business_date: Mapped[date] = mapped_column(Date)
    recipe_version: Mapped[int] = mapped_column(Integer)
    price_ex_vat_minor: Mapped[int] = mapped_column(Integer)
    cost_minor: Mapped[int] = mapped_column(Integer)
    gp_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    cm_minor: Mapped[int] = mapped_column(Integer)
    cost_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    units_sold: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal(0))
    total_contribution_minor: Mapped[int] = mapped_column(BigInteger, default=0)  # CM x units (FR-MNU-03)


class Anomaly(UUIDPk, Timestamps, SiteScoped, Base):
    __tablename__ = "anomaly"
    __table_args__ = (
        UniqueConstraint("site_id", "fingerprint", name="uq_anomaly_fingerprint"),
        Index("ix_anomaly_site_status", "site_id", "status", "created_at"),
        CheckConstraint("status IN ('open', 'investigating', 'dismissed', 'closed')", name="anomaly_status_valid"),
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="anomaly_severity_valid"),
    )

    detector: Mapped[str] = mapped_column(String(40))
    subject: Mapped[dict[str, Any]] = mapped_column(JSONB)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    fingerprint: Mapped[str] = mapped_column(String(64))
    streak: Mapped[int] = mapped_column(Integer, default=1)
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20), default="open")
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    weekly_impact_minor: Mapped[int] = mapped_column(Integer, default=0)
    dismissed_until: Mapped[date | None] = mapped_column(Date)
    # A same-day daypart drop folded into the site-level revenue anomaly it explains (no second case).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("anomaly.id", ondelete="SET NULL"))
    # Severity at the last investigation: a repeat only re-investigates when it escalates (FR-ANO-05).
    investigated_severity: Mapped[str | None] = mapped_column(String(16))


class Investigation(UUIDPk, Timestamps, SiteScoped, Base):
    __tablename__ = "investigation"
    __table_args__ = (
        Index("ix_investigation_anomaly", "anomaly_id", "version"),
        CheckConstraint("status IN ('complete', 'failed')", name="investigation_status_valid"),
    )

    anomaly_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("anomaly.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    finding: Mapped[str] = mapped_column(String(2000))
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    narrative: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="complete")
    draft_recommendations: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
