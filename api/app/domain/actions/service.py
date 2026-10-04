"""Recommendation workflow and the OperationsCase projection (FR-ACT-02..04, 08, 11, 13)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.audit import record_audit
from app.core.errors import Conflict
from app.core.tenancy.context import SiteContext
from app.domain.actions.impact import recompute
from app.domain.actions.models import CaseEvent, OperationsCase, Recommendation, RecommendationTransition
from app.domain.actions.rules import PENDING, TERMINAL, can_transition, derive_case_status
from app.domain.intelligence.models import Anomaly, Investigation

EVENT_FOR = {"proposed": "proposed", "approved": "approved", "rejected": "rejected", "expired": "expired",
             "superseded": "superseded", "executing": "executing", "completed": "executed", "failed": "failed",
             "follow_up": "follow_up_scheduled", "outcome_measured": "outcome_measured"}


def add_event(ctx: SiteContext, case_id: uuid.UUID, kind: str, summary: str, ref: dict[str, Any] | None = None,
              *, actor: str | None = None, at: datetime | None = None) -> None:
    ctx.session.add(CaseEvent(organisation_id=ctx.organisation_id, site_id=ctx.site_id, case_id=case_id,
                              at=at or datetime.now(UTC), actor=actor or ctx.actor, kind=kind,
                              summary=summary[:600], ref=ref or {}))


def cap(text: str) -> str:
    """Capitalise the first letter only (str.capitalize would lowercase supplier names)."""
    return text[:1].upper() + text[1:]


def rec_label(rec: Recommendation) -> str:
    return rec.parameters.get("title") or rec.type.replace("_", " ")


async def transition(ctx: SiteContext, rec: Recommendation, to_status: str, *, reason: str,
                     approved_by: str | None = None) -> Recommendation:
    if not can_transition(rec.status, to_status):
        raise Conflict(f"A recommendation in state {rec.status!r} cannot move to {to_status!r}.",
                       code="illegal_transition")
    before = {"status": rec.status, "version": rec.version}
    ctx.session.add(RecommendationTransition(
        organisation_id=ctx.organisation_id, site_id=ctx.site_id, recommendation_id=rec.id, from_status=rec.status,
        to_status=to_status, actor=ctx.actor, reason=reason[:600], at=datetime.now(UTC)))
    rec.status = to_status
    if to_status == "approved":
        rec.approved_by = approved_by or ctx.actor
        rec.approved_at = datetime.now(UTC)
    if to_status == "completed":
        rec.executed_at = datetime.now(UTC)
    record_audit(ctx.session, actor=ctx.actor, entity_type="recommendation", entity_id=rec.id,
                 action=f"transition:{to_status}", organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                 before=before, after={"status": to_status, "version": rec.version, "reason": reason[:200]})
    add_event(ctx, rec.case_id, EVENT_FOR.get(to_status, to_status), f"{cap(rec_label(rec))}: {reason}",
              {"type": "recommendation", "id": str(rec.id), "version": rec.version})
    await ctx.session.flush()
    await refresh_case(ctx, rec.case_id)
    return rec


async def adjust(ctx: SiteContext, rec: Recommendation, parameters: dict[str, Any], *, note: str | None = None
                 ) -> Recommendation:
    """FR-ACT-04: an approver adjusts parameters before approving; impact is recomputed, version bumped."""
    if rec.status != "proposed":
        raise Conflict("Only proposed recommendations can be adjusted.", code="illegal_transition")
    before = {"parameters": rec.parameters, "version": rec.version, "expected_impact_minor": rec.expected_impact_minor}
    allowed = set(rec.impact_inputs.get("adjustable", []))
    unknown = set(parameters) - allowed
    if unknown:
        raise Conflict(f"These parameters cannot be adjusted: {', '.join(sorted(unknown))}.", code="not_adjustable")
    rec.parameters = {**rec.parameters, **parameters}
    rec.expected_impact_minor, rec.impact_inputs = recompute(rec.type, rec.parameters, rec.impact_inputs)
    rec.version += 1
    if note:
        rec.notes = ((rec.notes + "\n") if rec.notes else "") + f"{ctx.actor}: {note}"
    record_audit(ctx.session, actor=ctx.actor, entity_type="recommendation", entity_id=rec.id, action="adjust",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id, before=before,
                 after={"parameters": rec.parameters, "version": rec.version,
                        "expected_impact_minor": rec.expected_impact_minor})
    ctx.session.add(RecommendationTransition(
        organisation_id=ctx.organisation_id, site_id=ctx.site_id, recommendation_id=rec.id, from_status="proposed",
        to_status="proposed", actor=ctx.actor, reason=f"Adjusted to version {rec.version}", at=datetime.now(UTC)))
    add_event(ctx, rec.case_id, "adjusted", f"{cap(rec_label(rec))} adjusted (version {rec.version}); "
              f"expected impact recomputed.", {"type": "recommendation", "id": str(rec.id), "version": rec.version})
    await ctx.session.flush()
    await refresh_case(ctx, rec.case_id)
    return rec


def subject_key(subject: dict[str, Any]) -> str:
    return f"{subject.get('type')}:{subject.get('id')}"


async def supersede_pending(ctx: SiteContext, rec_type: str, subject: dict[str, Any], *,
                            keep: uuid.UUID | None = None) -> int:
    """FR-ACT-08: a new recommendation for the same subject and type supersedes a pending one."""
    rows = (await ctx.session.execute(select(Recommendation).where(
        Recommendation.site_id == ctx.site_id, Recommendation.type == rec_type,
        Recommendation.status.in_(tuple(PENDING)), *([Recommendation.id != keep] if keep else [])))).scalars().all()
    n = 0
    for row in rows:
        if subject_key(row.subject) == subject_key(subject):
            await transition(ctx, row, "superseded", reason="Superseded by a newer recommendation.")
            n += 1
    return n


async def refresh_case(ctx: SiteContext, case_id: uuid.UUID) -> OperationsCase:
    """Recompute the derived status and ranking impact from the linked records (FR-ACT-11)."""
    case = (await ctx.session.execute(select(OperationsCase).where(OperationsCase.id == case_id))).scalar_one()
    recs = (await ctx.session.execute(select(Recommendation).where(Recommendation.case_id == case_id))).scalars().all()
    investigated = case.investigation_id is not None and (await ctx.session.execute(select(Investigation.status).where(
        Investigation.id == case.investigation_id))).scalar_one_or_none() == "complete"
    status = derive_case_status(investigated=investigated, rec_statuses=[r.status for r in recs])
    case.expected_impact_minor = sum(r.expected_impact_minor for r in recs if r.status not in TERMINAL)
    if status != case.status:
        case.status = status
        if status == "closed":
            case.closed_at = datetime.now(UTC)
            reasons = sorted({r.status for r in recs})
            case.closed_reason = case.closed_reason or f"All recommendations {', '.join(reasons)}."
            add_event(ctx, case.id, "closed", f"Case closed: {case.closed_reason}", {"type": "case", "id": str(case.id)})
            anomaly = (await ctx.session.execute(select(Anomaly).where(Anomaly.id == case.anomaly_id))).scalar_one()
            anomaly.status = "closed"
    await ctx.session.flush()
    return case
