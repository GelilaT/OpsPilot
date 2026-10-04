"""Operational memory: what happened, why, what was done and whether it worked (FR-MEM-01..03)."""

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.tenancy.scoping import SiteScoped
from app.ports.ai import EMBEDDING_DIMENSIONS

MEMORY_KINDS = ("investigation", "outcome")
NOTE_TARGETS = ("investigation", "recommendation", "case")


class MemoryEntry(UUIDPk, Timestamps, SiteScoped, Base):
    """One remembered case. `subject_keys` ("ingredient:<id>", "supplier:<id>", ...) drive structured
    candidate search; `embedding` (pgvector, Gemini text embedding of `summary`) drives similarity."""

    __tablename__ = "memory_entry"
    __table_args__ = (
        CheckConstraint("kind IN ('investigation', 'outcome')", name="kind_valid"),
        Index("uq_memory_entry_case_kind", "case_id", "kind", unique=True),
        Index("ix_memory_entry_subjects", "subject_keys", postgresql_using="gin"),
        Index("ix_memory_entry_site_cause", "site_id", "cause_code", "occurred_on"),
        Index("ix_memory_entry_embedding", "embedding", postgresql_using="ivfflat",
              postgresql_with={"lists": 10}, postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operations_case.id", ondelete="SET NULL"))
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investigation.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))
    subjects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # entity refs with names
    subject_keys: Mapped[list[str]] = mapped_column(ARRAY(String(120)), default=list)
    cause_code: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)  # templated from facts, never free AI text
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    occurred_on: Mapped[date] = mapped_column(Date)
    resolved_on: Mapped[date | None] = mapped_column(Date)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str | None] = mapped_column(String(80))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Note(UUIDPk, Timestamps, SiteScoped, Base):
    """A manager's note on an investigation, recommendation or case; it joins the case memory (FR-MEM-02)."""

    __tablename__ = "note"
    __table_args__ = (
        CheckConstraint("target_type IN ('investigation', 'recommendation', 'case')", name="target_valid"),
        Index("ix_note_target", "target_type", "target_id"),
    )

    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[uuid.UUID]
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operations_case.id", ondelete="CASCADE"))
    author: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(String(4000))
