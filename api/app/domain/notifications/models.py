"""Outbound email with recorded delivery status (FR-BRF-05)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.tenancy.scoping import SiteScoped

DELIVERY_STATUSES = ("pending", "accepted", "sent", "logged", "failed")


class EmailDelivery(UUIDPk, Timestamps, SiteScoped, Base):
    __tablename__ = "email_delivery"
    __table_args__ = (
        Index("uq_email_delivery_key", "idempotency_key", unique=True),
        Index("ix_email_delivery_site_created", "site_id", "created_at"),
        CheckConstraint("status IN ('pending', 'accepted', 'sent', 'logged', 'failed')", name="status_valid"),
    )

    idempotency_key: Mapped[str] = mapped_column(String(200))
    to: Mapped[list[str]] = mapped_column(JSONB)
    subject: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(String(20000))
    html_body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(2000))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    related_id: Mapped[uuid.UUID | None]
