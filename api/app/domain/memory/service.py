"""Operational memory: write, embed and retrieve (FR-MEM-01/02/03/05).

Retrieval (SRS 4.3):
    candidates = entries where subjects overlap OR cause_code matches, last 365 days, same site
    score = 0.5 * jaccard(subjects) + 0.3 * cosine(embedding, query_embedding) + 0.2 * 0.5 ** (age_days / 60)
    return top 3 with score >= 0.5

Summaries are templated from computed facts (never free AI text), and only retrieved entries may be cited
as history (FR-MEM-05): the investigation's "similar past cases" are exactly these records.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.core.tenancy.context import SiteContext
from app.domain.memory.models import MemoryEntry, Note
from app.ports import IntegrationKind

log = logging.getLogger("opspilot.memory")

WINDOW_DAYS = 365
HALF_LIFE_DAYS = 60
TOP_K = 3
MIN_SCORE = Decimal("0.5")
W_ENTITY, W_COSINE, W_RECENCY = Decimal("0.5"), Decimal("0.3"), Decimal("0.2")
EMBED_BATCH = 10


@dataclass(frozen=True)
class Recall:
    entry_id: uuid.UUID
    case_id: uuid.UUID | None
    occurred_on: date
    cause_code: str | None
    summary: str
    outcome: dict[str, Any] | None
    score: Decimal
    entity_overlap: Decimal
    cosine: Decimal
    recency: Decimal

    def as_facts(self) -> dict[str, Any]:
        return {"memory_id": str(self.entry_id), "case_id": str(self.case_id) if self.case_id else None,
                "date": self.occurred_on.isoformat(), "cause_code": self.cause_code, "summary": self.summary,
                "verdict": (self.outcome or {}).get("verdict"), "score": float(self.score),
                "entity_overlap": float(self.entity_overlap), "cosine": float(self.cosine),
                "recency": float(self.recency)}


def jaccard(a: set[str], b: set[str]) -> Decimal:
    return Decimal(len(a & b)) / Decimal(len(a | b)) if a | b else Decimal(0)


def recency(age_days: int) -> Decimal:
    return Decimal(str(0.5 ** (max(age_days, 0) / HALF_LIFE_DAYS)))


def score(overlap: Decimal, cosine: Decimal, age_days: int) -> Decimal:
    return (W_ENTITY * overlap + W_COSINE * max(cosine, Decimal(0)) + W_RECENCY * recency(age_days)).quantize(
        Decimal("0.0001"))


async def embed(ctx: SiteContext, text: str) -> tuple[list[float] | None, str | None]:
    """Embedding through the site's AIPort; degraded mode (None) when the provider is unavailable."""
    try:
        ai = await ctx.adapter(IntegrationKind.ai)
        vector, info = await ai.embed(text)
        return vector, info.model
    except Exception:  # any provider failure degrades to structured-only retrieval
        log.warning("memory embedding unavailable", exc_info=True)
        return None, None


async def ensure_embeddings(ctx: SiteContext, entries: list[MemoryEntry]) -> None:
    for entry in [e for e in entries if e.embedding is None][:EMBED_BATCH]:
        vector, model = await embed(ctx, entry.summary + ("\n" + entry.notes if entry.notes else ""))
        if vector is not None:
            entry.embedding, entry.embedding_model, entry.embedded_at = vector, model, datetime.now(UTC)
    await ctx.session.flush()


async def retrieve(ctx: SiteContext, *, subjects: set[str], cause_code: str | None, query_text: str, on: date,
                   exclude_case_id: uuid.UUID | None = None) -> list[Recall]:
    since = on - timedelta(days=WINDOW_DAYS)
    conds = [MemoryEntry.subject_keys.overlap(sorted(subjects))] if subjects else []
    if cause_code:
        conds.append(MemoryEntry.cause_code == cause_code)
    if not conds:
        return []
    q = select(MemoryEntry).where(MemoryEntry.site_id == ctx.site_id, MemoryEntry.occurred_on.between(since, on),
                                  or_(*conds))
    if exclude_case_id is not None:
        q = q.where((MemoryEntry.case_id.is_(None)) | (MemoryEntry.case_id != exclude_case_id))
    candidates = list((await ctx.session.execute(q)).scalars().all())
    if not candidates:
        return []
    await ensure_embeddings(ctx, candidates)
    query_vec, _ = await embed(ctx, query_text)
    cos: dict[uuid.UUID, Decimal] = {}
    if query_vec is not None:
        ids = [c.id for c in candidates if c.embedding is not None]
        if ids:
            for i, dist in (await ctx.session.execute(select(
                    MemoryEntry.id, MemoryEntry.embedding.cosine_distance(query_vec)).where(MemoryEntry.id.in_(ids)))).all():
                cos[i] = (Decimal(1) - Decimal(str(dist))).quantize(Decimal("0.0001"))
    out = []
    for c in candidates:
        overlap = jaccard(subjects, set(c.subject_keys))
        cosine = cos.get(c.id, Decimal(0))
        age = (on - c.occurred_on).days
        s = score(overlap, cosine, age)
        if s >= MIN_SCORE:
            out.append(Recall(c.id, c.case_id, c.occurred_on, c.cause_code, c.summary, c.outcome, s,
                              overlap.quantize(Decimal("0.0001")), cosine, recency(age).quantize(Decimal("0.0001"))))
    out.sort(key=lambda r: r.score, reverse=True)
    return out[:TOP_K]


async def case_notes(ctx: SiteContext, case_id: uuid.UUID) -> str | None:
    rows = (await ctx.session.execute(select(Note.author, Note.text, Note.created_at).where(
        Note.case_id == case_id).order_by(Note.created_at))).all()
    return "\n".join(f"{a}: {t}" for a, t, _ in rows) or None


async def upsert_entry(ctx: SiteContext, *, case_id: uuid.UUID | None, kind: str, investigation_id: uuid.UUID | None,
                       subjects: list[dict[str, Any]], cause_code: str | None, summary: str,
                       actions: list[dict[str, Any]], outcome: dict[str, Any] | None, occurred_on: date,
                       resolved_on: date | None = None) -> MemoryEntry:
    """FR-MEM-01: one entry per case and kind; rewriting it clears the embedding so it is re-embedded."""
    entry = None
    if case_id is not None:
        entry = (await ctx.session.execute(select(MemoryEntry).where(
            MemoryEntry.case_id == case_id, MemoryEntry.kind == kind))).scalar_one_or_none()
    if entry is None:
        entry = MemoryEntry(organisation_id=ctx.organisation_id, site_id=ctx.site_id, case_id=case_id, kind=kind)
        ctx.session.add(entry)
    entry.investigation_id = investigation_id
    entry.subjects = subjects
    entry.subject_keys = sorted({f"{s['type']}:{s['id']}" for s in subjects})
    entry.cause_code = cause_code
    entry.summary = summary
    entry.actions = actions
    entry.outcome = outcome
    entry.occurred_on = occurred_on
    entry.resolved_on = resolved_on
    entry.notes = await case_notes(ctx, case_id) if case_id else None
    entry.embedding = None
    entry.embedding_model = None
    await ctx.session.flush()
    return entry


async def refresh_notes(ctx: SiteContext, case_id: uuid.UUID) -> None:
    """FR-MEM-02: a note joins the case's memory entries (and their embeddings are refreshed)."""
    notes = await case_notes(ctx, case_id)
    for entry in (await ctx.session.execute(select(MemoryEntry).where(MemoryEntry.case_id == case_id))).scalars():
        entry.notes = notes
        entry.embedding = None
    await ctx.session.flush()


async def recurring(ctx: SiteContext, *, subject_key: str, cause_code: str, on: date) -> int:
    """Entries with the same subject and cause in the last 90 days (FR-MEM-04 input)."""
    return int((await ctx.session.execute(select(func.count()).select_from(MemoryEntry).where(
        MemoryEntry.site_id == ctx.site_id, MemoryEntry.cause_code == cause_code,
        MemoryEntry.subject_keys.contains([subject_key]), MemoryEntry.occurred_on >= on - timedelta(days=90)))).scalar() or 0)
