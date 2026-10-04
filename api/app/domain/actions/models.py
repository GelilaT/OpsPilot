"""Action Centre persistence (FR-ACT-01-13)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.tenancy.scoping import SiteScoped

REC_TYPES = (
    "purchase_order",
    "supplier_switch",
    "par_level_change",
    "price_review",
    "staffing_change",
    "waste_reduction",
    "investigate_task",
)
REC_STATUSES = (
    "draft",
    "proposed",
    "approved",
    "rejected",
    "expired",
    "superseded",
    "executing",
    "completed",
    "failed",
    "follow_up",
    "outcome_measured",
)
CASE_STATUSES = ("detected", "investigating", "awaiting_approval", "executing", "monitoring", "closed")
RISKS = ("low", "medium", "high")
ROLES = ("owner", "general_manager", "head_chef", "shift_manager")


class OperationsCase(UUIDPk, Timestamps, SiteScoped, Base):
    __tablename__ = "operations_case"
    __table_args__ = (
        UniqueConstraint("anomaly_id", name="uq_operations_case_anomaly"),
        Index("ix_operations_case_site_status", "site_id", "status", "updated_at"),
        CheckConstraint(
            "status IN ('detected', 'investigating', 'awaiting_approval', 'executing', 'monitoring', 'closed')",
            name="operations_case_status_valid",
        ),
    )

    anomaly_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("anomaly.id", ondelete="CASCADE"))
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investigation.id", ondelete="SET NULL"))
    # Cached projection of the linked records; always recomputed by `derive_case_status` (FR-ACT-11).
    status: Mapped[str] = mapped_column(String(24), default="detected")
    closed_reason: Mapped[str | None] = mapped_column(String(400))
    expected_impact_minor: Mapped[int] = mapped_column(BigInteger, default=0)  # dashboard ranking (FR-ACT-13)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


CASE_EVENT_KINDS = (
    "detected", "investigated", "proposed", "approved", "rejected", "adjusted", "expired", "superseded",
    "executing", "executed", "failed", "follow_up_scheduled", "outcome_measured", "memory_written", "note", "closed",
)


class CaseEvent(UUIDPk, SiteScoped, Base):
    """One agent or human step on a case, with its evidence link (FR-ACT-13)."""

    __tablename__ = "case_event"
    __table_args__ = (Index("ix_case_event_case_at", "case_id", "at"),)

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("operations_case.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(String(600))
    ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # {"type": ..., "id": ...}


class Recommendation(UUIDPk, Timestamps, SiteScoped, Base):
    __tablename__ = "recommendation"
    __table_args__ = (
        Index("ix_recommendation_case", "case_id", "status"),
        Index("ix_recommendation_site_status", "site_id", "status", "created_at"),
        CheckConstraint(
            "type IN ('purchase_order', 'supplier_switch', 'par_level_change', 'price_review', "
            "'staffing_change', 'waste_reduction', 'investigate_task')",
            name="recommendation_type_valid",
        ),
        CheckConstraint(
            "status IN ('draft', 'proposed', 'approved', 'rejected', 'expired', 'superseded', "
            "'executing', 'completed', 'failed', 'follow_up', 'outcome_measured')",
            name="recommendation_status_valid",
        ),
        CheckConstraint("risk IN ('low', 'medium', 'high')", name="recommendation_risk_valid"),
        CheckConstraint(
            "required_role IN ('owner', 'general_manager', 'head_chef', 'shift_manager')",
            name="recommendation_role_valid",
        ),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("operations_case.id", ondelete="CASCADE"))
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investigation.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(32))
    subject: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    expected_impact_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    impact_inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    confidence: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    risk: Mapped[str] = mapped_column(String(8), default="medium")
    required_role: Mapped[str] = mapped_column(String(20), default="general_manager")
    evidence_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    success_metric: Mapped[str | None] = mapped_column(String(120))
    follow_up_at: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(String(600))
    notes: Mapped[str | None] = mapped_column(String(2000))  # risk notes and adjustment notes
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecommendationTransition(UUIDPk, SiteScoped, Base):
    __tablename__ = "recommendation_transition"
    __table_args__ = (Index("ix_recommendation_transition_rec", "recommendation_id", "at"),)

    recommendation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recommendation.id", ondelete="CASCADE"))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(String(600))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecommendationExecution(UUIDPk, SiteScoped, Base):
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_recommendation_execution_key"),
        Index("ix_recommendation_execution_rec", "recommendation_id"),
    )
    __tablename__ = "recommendation_execution"

    recommendation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recommendation.id", ondelete="CASCADE"))
    recommendation_version: Mapped[int] = mapped_column(Integer)
    executor: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    success: Mapped[bool] = mapped_column(default=True)
    error: Mapped[str | None] = mapped_column(String(2000))
    at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OpsTask(UUIDPk, Timestamps, SiteScoped, Base):
    __tablename__ = "ops_task"
    __table_args__ = (Index("ix_ops_task_site_status", "site_id", "status"),)

    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recommendation.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(16), default="open")
    assignee_role: Mapped[str] = mapped_column(String(20), default="general_manager")
    due_on: Mapped[date | None] = mapped_column(Date)
    closed_note: Mapped[str | None] = mapped_column(String(2000))


VERDICTS = ("improved", "no_change", "worsened")


class RecommendationOutcome(UUIDPk, Timestamps, SiteScoped, Base):
    """Measured effect of an executed recommendation against its counterfactual (FR-ACT-07)."""

    __tablename__ = "recommendation_outcome"
    __table_args__ = (
        UniqueConstraint("recommendation_id", name="uq_recommendation_outcome_rec"),
        CheckConstraint("verdict IN ('improved', 'no_change', 'worsened')", name="verdict_valid"),
    )

    recommendation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recommendation.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("operations_case.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(String(120))
    pre_start: Mapped[date] = mapped_column(Date)
    post_start: Mapped[date] = mapped_column(Date)
    post_end: Mapped[date] = mapped_column(Date)
    counterfactual: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    actual: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    effect: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    effect_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    expected_effect: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    sigma: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    verdict: Mapped[str] = mapped_column(String(16))
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
