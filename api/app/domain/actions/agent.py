"""The case agent (FR-ACT-11/12): detect -> investigate -> recommend -> human approval -> execute -> measure.

The agent advances every case without prompting; approval is the only mandatory manual step. Approval
enqueues `action.execute` in the same transaction (FR-JOB-01); the executor runs in the worker, and the
follow-up date it sets is picked up by the 06:00 outcome evaluation.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.errors import Conflict, Forbidden
from app.core.jobs import enqueue, job_key
from app.core.tenancy.context import SiteContext
from app.domain.actions.executors import execute, execution_key
from app.domain.actions.generators import generate
from app.domain.actions.models import OperationsCase, Recommendation
from app.domain.actions.service import add_event, cap, rec_label, refresh_case, supersede_pending, transition
from app.domain.intelligence.models import Anomaly, Investigation
from app.domain.purchasing.invoice_rules import ROLE_RANK


def describe_anomaly(a: Anomaly) -> str:
    f = a.facts
    what = a.subject.get("name") or a.detector.replace("_", " ")
    if f.get("deviation_pct") is not None:
        return f"{a.detector.replace('_', ' ').capitalize()}: {what} {f['deviation_pct']}% vs baseline ({a.severity})."
    return f"{a.detector.replace('_', ' ').capitalize()}: {what} ({a.severity})."


async def open_case(ctx: SiteContext, anomaly: Anomaly) -> OperationsCase:
    case = (await ctx.session.execute(select(OperationsCase).where(
        OperationsCase.anomaly_id == anomaly.id))).scalar_one_or_none()
    if case is not None:
        return case
    case = OperationsCase(organisation_id=ctx.organisation_id, site_id=ctx.site_id, anomaly_id=anomaly.id,
                          status="detected")
    ctx.session.add(case)
    await ctx.session.flush()
    add_event(ctx, case.id, "detected", describe_anomaly(anomaly), {"type": "anomaly", "id": str(anomaly.id)},
              actor="agent")
    return case


async def after_investigation(ctx: SiteContext, case: OperationsCase, inv: Investigation, anomaly: Anomaly
                              ) -> list[Recommendation]:
    """The investigation proposes recommendations (superseding pending ones for the same subject and type)."""
    case.investigation_id = inv.id
    causes = inv.narrative.get("causes", [])
    summary = (f"Investigation v{inv.version}: {causes[0]['label']} (confidence {causes[0]['confidence']:.2f})."
               if causes else f"Investigation v{inv.version}: no cause above the threshold.")
    add_event(ctx, case.id, "investigated", summary, {"type": "investigation", "id": str(inv.id)}, actor="agent")
    await ctx.session.flush()
    recs = await generate(ctx, inv, anomaly, case.id)
    for rec in recs:
        ctx.session.add(rec)
        await ctx.session.flush()
        await supersede_pending(ctx, rec.type, rec.subject, keep=rec.id)
        await transition(ctx, rec, "proposed", reason=_proposal_reason(rec))
    await refresh_case(ctx, case.id)
    return recs


def _proposal_reason(rec: Recommendation) -> str:
    return f"proposed by the agent; expected impact {rec.expected_impact_minor / 100:.2f} per week"


def require_role(role: str, rec: Recommendation) -> None:
    if ROLE_RANK.get(role, 0) < ROLE_RANK.get(rec.required_role, 99):
        raise Forbidden(f"This action requires the {rec.required_role.replace('_', ' ')} role.", code="approval_limit")


async def approve(ctx: SiteContext, rec: Recommendation, *, role: str, note: str | None = None) -> Recommendation:
    require_role(role, rec)
    if rec.status != "proposed":
        raise Conflict(f"Cannot approve a recommendation in state {rec.status!r}.", code="illegal_transition")
    if rec.expires_at and rec.expires_at < datetime.now(UTC):
        await transition(ctx, rec, "expired", reason="expired before approval")
        raise Conflict("This recommendation has expired.", code="expired")
    if note:
        rec.notes = ((rec.notes + "\n") if rec.notes else "") + f"{ctx.actor}: {note}"
    await transition(ctx, rec, "approved", reason=f"approved by {ctx.actor}", approved_by=ctx.actor)
    await enqueue(ctx.session, "action.execute", key=job_key("action.execute", rec.id, rec.version),
                  lock=f"recommendation:{rec.id}",
                  args={"organisation_id": str(ctx.organisation_id), "site_id": str(ctx.site_id),
                        "recommendation_id": str(rec.id), "version": rec.version, "approver_role": role,
                        "actor": ctx.actor})
    return rec


async def reject(ctx: SiteContext, rec: Recommendation, *, role: str, reason: str) -> Recommendation:
    require_role(role, rec)
    rec.rejection_reason = reason
    await transition(ctx, rec, "rejected", reason=reason)
    await remember_if_closed(ctx, rec.case_id)
    return rec


async def remember_if_closed(ctx: SiteContext, case_id: uuid.UUID) -> None:
    """A case closed by rejection or expiry still becomes memory, with the reason recorded (FR-ACT-12)."""
    from app.domain.outcomes.evaluator import write_case_memory

    case = (await ctx.session.execute(select(OperationsCase).where(OperationsCase.id == case_id))).scalar_one()
    if case.status == "closed":
        await write_case_memory(ctx, case_id, kind="investigation")


async def run_execution(ctx: SiteContext, rec_id: uuid.UUID, version: int, approver_role: str) -> Recommendation:
    """Worker side of approval: executing -> completed -> follow_up (or failed)."""
    rec = (await ctx.session.execute(select(Recommendation).where(
        Recommendation.id == rec_id).with_for_update())).scalar_one()
    if rec.version != version or rec.status not in ("approved", "executing"):
        return rec  # replay after completion, or a stale job: nothing to do
    if rec.status == "approved":
        await transition(ctx, rec, "executing", reason=f"executor started ({execution_key(rec)})")
    try:
        async with ctx.session.begin_nested():
            row = await execute(ctx, rec, approver_role=approver_role)
    except Exception as exc:
        rec.notes = ((rec.notes + "\n") if rec.notes else "") + f"Execution failed: {exc}"[:500]
        await transition(ctx, rec, "failed", reason=f"execution failed: {str(exc)[:200]}")
        return rec
    add_event(ctx, rec.case_id, "executed", f"{cap(rec_label(rec))} executed.",
              {"type": "recommendation_execution", "id": str(row.id), "result": row.result}, actor="agent")
    await transition(ctx, rec, "completed", reason="execution finished")
    follow_up = (await ctx.today()) + timedelta(days=ctx.config.get("actions.follow_up_days"))
    rec.follow_up_at = follow_up
    await transition(ctx, rec, "follow_up", reason=f"outcome to be measured on {follow_up.isoformat()} "
                                                   f"({rec.success_metric})")
    return rec


async def expire_due(ctx: SiteContext) -> int:
    rows = (await ctx.session.execute(select(Recommendation).where(
        Recommendation.site_id == ctx.site_id, Recommendation.status == "proposed",
        Recommendation.expires_at < datetime.now(UTC)))).scalars().all()
    for rec in rows:
        await transition(ctx, rec, "expired", reason="no decision before expiry")
    for case_id in {r.case_id for r in rows}:
        await remember_if_closed(ctx, case_id)
    return len(rows)


async def run_after_investigation(ctx: SiteContext, anomaly: Anomaly, inv: Investigation) -> OperationsCase:
    case = await open_case(ctx, anomaly)
    await after_investigation(ctx, case, inv, anomaly)
    return case
