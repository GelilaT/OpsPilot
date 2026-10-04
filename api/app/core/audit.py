"""Append-only audit trail written in the same transaction as the change (FR-API-05, FR-SET-03)."""

import dataclasses
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.context import job_id_var, request_id_var
from app.core.db import Base


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_org_at", "organisation_id", "at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    organisation_id: Mapped[uuid.UUID | None]
    site_id: Mapped[uuid.UUID | None]
    actor: Mapped[str] = mapped_column(String(120))  # "user:<id>" or "system:<job>"
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(60))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))
    job_id: Mapped[str | None] = mapped_column(String(64))


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "__table__"):  # SQLAlchemy entity
        return snapshot(value)
    return str(value)


def snapshot(entity: Any) -> dict[str, Any]:
    """Column values of an ORM entity, JSON-safe; used for audit before/after."""
    return {c.key: to_jsonable(getattr(entity, c.key, None)) for c in entity.__table__.columns}


def record_audit(
    session: AsyncSession,
    *,
    actor: str,
    entity_type: str,
    entity_id: Any,
    action: str,
    organisation_id: uuid.UUID | None,
    site_id: uuid.UUID | None = None,
    before: Any = None,
    after: Any = None,
) -> AuditEvent:
    event = AuditEvent(
        organisation_id=organisation_id,
        site_id=site_id,
        actor=actor,
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        before=to_jsonable(before),
        after=to_jsonable(after),
        request_id=request_id_var.get(),
        job_id=job_id_var.get(),
    )
    session.add(event)
    return event
