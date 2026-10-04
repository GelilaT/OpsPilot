"""Action Centre API (FR-ACT-02..09): queue by impact x confidence, detail with evidence and impact formula,
approve / reject / adjust with optimistic concurrency, and the measured outcome."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import site_context
from app.core.errors import NotFound, PreconditionFailed
from app.core.security import Role
from app.core.tenancy.context import SiteContext
from app.core.tenancy.services import actor_label, actor_names
from app.domain.actions import agent
from app.domain.actions.models import (
    Recommendation,
    RecommendationExecution,
    RecommendationOutcome,
    RecommendationTransition,
)
from app.domain.actions.service import adjust
from app.domain.intelligence.models import Investigation

router = APIRouter(prefix="/actions", tags=["actions"])
Reader = Annotated[SiteContext, Depends(site_context(Role.shift_manager))]


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    investigation_id: uuid.UUID | None
    type: str
    subject: dict[str, Any]
    status: str
    expected_impact_minor: int
    impact_inputs: dict[str, Any]
    confidence: Decimal
    risk: str
    notes: str | None
    required_role: str
    parameters: dict[str, Any]
    evidence_ref: dict[str, Any]
    success_metric: str | None
    follow_up_at: date | None = None
    expires_at: datetime | None
    version: int
    approved_by: str | None
    approved_by_name: str | None = None
    approved_at: datetime | None
    executed_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    queue_score: int = 0


class TransitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    from_status: str | None
    to_status: str
    actor: str
    reason: str
    at: datetime


class OutcomeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    recommendation_id: uuid.UUID
    metric: str
    pre_start: date
    post_start: date
    post_end: date
    counterfactual: Decimal
    actual: Decimal
    effect: Decimal
    effect_pct: Decimal | None
    expected_effect: Decimal
    sigma: Decimal
    verdict: str
    facts: dict[str, Any]


class RecommendationDetail(RecommendationOut):
    history: list[TransitionOut] = []
    execution: dict[str, Any] | None = None
    outcome: OutcomeOut | None = None
    evidence: list[dict[str, Any]] = []
    finding: str | None = None


class AdjustIn(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(None, max_length=600)


class ApproveIn(BaseModel):
    note: str | None = Field(None, max_length=600)


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=600)


def queue_score(rec: Recommendation) -> int:
    return int(rec.expected_impact_minor * float(rec.confidence))


def _out(rec: Recommendation) -> RecommendationOut:
    return RecommendationOut.model_validate(rec).model_copy(update={"queue_score": queue_score(rec)})


def role_of(ctx: SiteContext) -> str:
    return str(getattr(ctx, "role", "shift_manager"))


async def _load(ctx: SiteContext, action_id: uuid.UUID, *, lock: bool = False) -> Recommendation:
    q = select(Recommendation).where(Recommendation.id == action_id, Recommendation.site_id == ctx.site_id)
    rec = (await ctx.session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if rec is None:
        raise NotFound("Recommendation not found.", code="recommendation_not_found")
    return rec


def _check_version(rec: Recommendation, if_match: str | None) -> None:
    if if_match is not None and if_match.strip('"W/') != str(rec.version):
        raise PreconditionFailed("The recommendation changed; reload and try again.", code="stale_version")


@router.get("", response_model=list[RecommendationOut])
async def list_actions(ctx: Reader, status: str | None = None, type: str | None = None,
                       case_id: uuid.UUID | None = None, limit: int = Query(100, le=500)):
    q = select(Recommendation).where(Recommendation.site_id == ctx.site_id)
    if status:
        q = q.where(Recommendation.status.in_(status.split(",")))
    if type:
        q = q.where(Recommendation.type.in_(type.split(",")))
    if case_id:
        q = q.where(Recommendation.case_id == case_id)
    rows = list((await ctx.session.execute(q.order_by(Recommendation.created_at.desc()).limit(limit))).scalars())
    rows.sort(key=lambda r: -queue_score(r))
    return [_out(r) for r in rows]


@router.get("/{action_id}", response_model=RecommendationDetail)
async def get_action(action_id: uuid.UUID, ctx: Reader):
    rec = await _load(ctx, action_id)
    history = (await ctx.session.execute(select(RecommendationTransition).where(
        RecommendationTransition.recommendation_id == rec.id).order_by(RecommendationTransition.at))).scalars().all()
    execution = (await ctx.session.execute(select(RecommendationExecution).where(
        RecommendationExecution.recommendation_id == rec.id).order_by(
        RecommendationExecution.recommendation_version.desc()).limit(1))).scalar_one_or_none()
    outcome = (await ctx.session.execute(select(RecommendationOutcome).where(
        RecommendationOutcome.recommendation_id == rec.id))).scalar_one_or_none()
    inv = (await ctx.session.execute(select(Investigation).where(
        Investigation.id == rec.investigation_id))).scalar_one_or_none() if rec.investigation_id else None
    names = await actor_names(ctx.session, [rec.approved_by, *(h.actor for h in history)])
    return RecommendationDetail(
        **{**_out(rec).model_dump(), "approved_by_name": actor_label(names, rec.approved_by)},
        history=[TransitionOut.model_validate(h).model_copy(update={"actor": actor_label(names, h.actor) or h.actor})
                 for h in history],
        execution={"key": execution.idempotency_key, "result": execution.result, "success": execution.success,
                   "at": execution.at} if execution else None,
        outcome=OutcomeOut.model_validate(outcome) if outcome else None,
        evidence=inv.graph.get("nodes", []) if inv else [], finding=inv.finding if inv else None)


@router.get("/{action_id}/outcome", response_model=OutcomeOut)
async def get_outcome(action_id: uuid.UUID, ctx: Reader):
    await _load(ctx, action_id)
    outcome = (await ctx.session.execute(select(RecommendationOutcome).where(
        RecommendationOutcome.recommendation_id == action_id))).scalar_one_or_none()
    if outcome is None:
        raise NotFound("No outcome measured yet.", code="outcome_not_measured")
    return outcome


@router.post("/{action_id}/approve", response_model=RecommendationOut)
async def approve(action_id: uuid.UUID, ctx: Reader, body: ApproveIn | None = None,
                  if_match: Annotated[str | None, Header()] = None):
    rec = await _load(ctx, action_id, lock=True)
    _check_version(rec, if_match)
    rec = await agent.approve(ctx, rec, role=role_of(ctx), note=body.note if body else None)
    return _out(rec)


@router.post("/{action_id}/reject", response_model=RecommendationOut)
async def reject(action_id: uuid.UUID, body: RejectIn, ctx: Reader, if_match: Annotated[str | None, Header()] = None):
    rec = await _load(ctx, action_id, lock=True)
    _check_version(rec, if_match)
    return _out(await agent.reject(ctx, rec, role=role_of(ctx), reason=body.reason))


@router.post("/{action_id}/adjust", response_model=RecommendationOut)
async def adjust_action(action_id: uuid.UUID, body: AdjustIn, ctx: Reader,
                        if_match: Annotated[str | None, Header()] = None):
    rec = await _load(ctx, action_id, lock=True)
    _check_version(rec, if_match)
    agent.require_role(role_of(ctx), rec)
    return _out(await adjust(ctx, rec, body.parameters, note=body.note))
