"""Operations cases (FR-ACT-11/13): open cases ranked by expected impact, detail and the agent timeline."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case as sql_case
from sqlalchemy import select

from app.api.deps import site_context
from app.api.v1.actions import RecommendationOut, _out
from app.core.errors import NotFound
from app.core.security import Role
from app.core.tenancy.context import SiteContext
from app.core.tenancy.services import actor_label, actor_names
from app.domain.actions.models import CaseEvent, OperationsCase, Recommendation, RecommendationOutcome
from app.domain.intelligence.models import Anomaly, Investigation
from app.domain.memory.models import MemoryEntry, Note

router = APIRouter(prefix="/cases", tags=["cases"])
Reader = Annotated[SiteContext, Depends(site_context(Role.shift_manager))]


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    anomaly_id: uuid.UUID
    investigation_id: uuid.UUID | None
    status: str
    closed_reason: str | None
    expected_impact_minor: int
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    title: str | None = None
    severity: str | None = None
    detector: str | None = None
    top_cause: str | None = None
    confidence: float | None = None
    pending_approvals: int = 0


class TimelineEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    at: datetime
    actor: str
    actor_name: str | None = None
    kind: str
    summary: str
    ref: dict[str, Any]


class CaseDetail(CaseOut):
    anomaly: dict[str, Any]
    investigation: dict[str, Any] | None
    recommendations: list[RecommendationOut]
    outcomes: list[dict[str, Any]]
    memory: list[dict[str, Any]]
    notes: list[dict[str, Any]]


ORDER = sql_case({"awaiting_approval": 0, "executing": 1, "investigating": 2, "detected": 3, "monitoring": 4,
                  "closed": 5}, value=OperationsCase.status, else_=9)


async def _summaries(ctx: SiteContext, cases: list[OperationsCase]) -> list[CaseOut]:
    if not cases:
        return []
    anomalies = {a.id: a for a in (await ctx.session.execute(select(Anomaly).where(
        Anomaly.id.in_([c.anomaly_id for c in cases])))).scalars()}
    invs = {i.id: i for i in (await ctx.session.execute(select(Investigation).where(
        Investigation.id.in_([c.investigation_id for c in cases if c.investigation_id])))).scalars()}
    pending: dict[uuid.UUID, int] = {}
    for case_id, in (await ctx.session.execute(select(Recommendation.case_id).where(
            Recommendation.case_id.in_([c.id for c in cases]), Recommendation.status == "proposed"))).all():
        pending[case_id] = pending.get(case_id, 0) + 1
    out = []
    for c in cases:
        a = anomalies[c.anomaly_id]
        inv = invs.get(c.investigation_id) if c.investigation_id else None
        causes = (inv.narrative.get("causes") if inv else None) or []
        out.append(CaseOut.model_validate(c).model_copy(update={
            "title": inv.finding.split(". ")[0] if inv else (a.subject.get("name") or a.detector),
            "severity": a.severity, "detector": a.detector,
            "top_cause": causes[0]["label"] if causes else None,
            "confidence": causes[0]["confidence"] if causes else None, "pending_approvals": pending.get(c.id, 0)}))
    return out


@router.get("", response_model=list[CaseOut])
async def list_cases(ctx: Reader, status: str | None = None, limit: int = Query(50, le=200)):
    """Open cases awaiting approval first, ranked by expected impact (FR-ACT-13)."""
    q = select(OperationsCase).where(OperationsCase.site_id == ctx.site_id)
    if status:
        q = q.where(OperationsCase.status.in_(status.split(",")))
    rows = (await ctx.session.execute(q.order_by(ORDER, OperationsCase.expected_impact_minor.desc(),
                                                 OperationsCase.updated_at.desc()).limit(limit))).scalars().all()
    return await _summaries(ctx, list(rows))


async def _case(ctx: SiteContext, case_id: uuid.UUID) -> OperationsCase:
    case = (await ctx.session.execute(select(OperationsCase).where(
        OperationsCase.id == case_id, OperationsCase.site_id == ctx.site_id))).scalar_one_or_none()
    if case is None:
        raise NotFound("Case not found.", code="case_not_found")
    return case


@router.get("/{case_id}", response_model=CaseDetail)
async def get_case(case_id: uuid.UUID, ctx: Reader):
    case = await _case(ctx, case_id)
    summary = (await _summaries(ctx, [case]))[0]
    a = (await ctx.session.execute(select(Anomaly).where(Anomaly.id == case.anomaly_id))).scalar_one()
    inv = (await ctx.session.execute(select(Investigation).where(
        Investigation.id == case.investigation_id))).scalar_one_or_none() if case.investigation_id else None
    recs = (await ctx.session.execute(select(Recommendation).where(Recommendation.case_id == case.id))).scalars().all()
    outcomes = (await ctx.session.execute(select(RecommendationOutcome).where(
        RecommendationOutcome.case_id == case.id))).scalars().all()
    memory = (await ctx.session.execute(select(MemoryEntry).where(MemoryEntry.case_id == case.id))).scalars().all()
    notes = (await ctx.session.execute(select(Note).where(Note.case_id == case.id).order_by(Note.created_at))).scalars()
    return CaseDetail(
        **summary.model_dump(),
        anomaly={"id": a.id, "detector": a.detector, "subject": a.subject, "severity": a.severity, "facts": a.facts,
                 "period_start": a.period_start, "period_end": a.period_end, "streak": a.streak},
        investigation={"id": inv.id, "version": inv.version, "finding": inv.finding, "confidence": inv.confidence,
                       "causes": inv.narrative.get("causes", []), "similar_cases": inv.narrative.get("similar_cases", [])}
        if inv else None,
        recommendations=sorted((_out(r) for r in recs), key=lambda r: -r.queue_score),
        outcomes=[{"recommendation_id": o.recommendation_id, "metric": o.metric, "verdict": o.verdict,
                   "effect_pct": o.effect_pct, "counterfactual": o.counterfactual, "actual": o.actual} for o in outcomes],
        memory=[{"id": m.id, "kind": m.kind, "summary": m.summary, "outcome": m.outcome} for m in memory],
        notes=[{"id": n.id, "author": n.author, "text": n.text, "created_at": n.created_at} for n in notes],
    )


@router.get("/{case_id}/timeline", response_model=list[TimelineEvent])
async def timeline(case_id: uuid.UUID, ctx: Reader):
    """Every agent and human step with timestamp, actor and evidence link (FR-ACT-13)."""
    case = await _case(ctx, case_id)
    rows = (await ctx.session.execute(select(CaseEvent).where(CaseEvent.case_id == case.id).order_by(
        CaseEvent.at, CaseEvent.id))).scalars().all()
    names = await actor_names(ctx.session, [r.actor for r in rows])
    return [TimelineEvent.model_validate(r).model_copy(update={"actor_name": actor_label(names, r.actor)}) for r in rows]
