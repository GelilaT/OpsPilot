"""Scheduled site jobs (FR-JOB-05): nightly pipeline (02:00), outcomes (06:00), briefs (07:00, Monday recap), follow-ups (16:00);
and the agent's work queue: recommendation execution and email delivery."""

import uuid
from datetime import date
from typing import Any

from app.core.tenancy.context import build_site_context
from app.core.tenancy.scoping import tenant_unit_of_work
from app.workers.runtime import BackoffRetry, site_task


async def execute_nightly_pipeline(*, organisation_id: str, site_id: str, business_date: str | None = None,
                                   ) -> dict[str, Any]:
    from app.domain.intelligence.pipeline import run_nightly

    org, site = uuid.UUID(organisation_id), uuid.UUID(site_id)
    async with tenant_unit_of_work(org, site) as session:
        ctx = await build_site_context(session, org, site, actor="system:nightly")
        day = date.fromisoformat(business_date) if business_date else await ctx.today()
        return (await run_nightly(ctx, day)).as_dict()


@site_task("nightly.pipeline", retry=2)
async def nightly_pipeline(*, organisation_id: str, site_id: str, business_date: str | None = None,
                           **_: Any) -> dict[str, Any]:
    return await execute_nightly_pipeline(organisation_id=organisation_id, site_id=site_id,
                                          business_date=business_date)


@site_task("action.execute", retry=BackoffRetry((2, 8, 32)))
async def action_execute(*, organisation_id: str, site_id: str, recommendation_id: str, version: int,
                         approver_role: str, actor: str = "agent", **_: Any) -> dict[str, Any]:
    """FR-ACT-05: run the executor for an approved recommendation (idempotent on id:version)."""
    from app.domain.actions.agent import run_execution

    org, site = uuid.UUID(organisation_id), uuid.UUID(site_id)
    async with tenant_unit_of_work(org, site) as session:
        ctx = await build_site_context(session, org, site, actor=actor)
        rec = await run_execution(ctx, uuid.UUID(recommendation_id), int(version), approver_role)
        return {"recommendation_id": recommendation_id, "status": rec.status}


@site_task("email.send", retry=BackoffRetry((2, 8, 32)))
async def email_send(*, organisation_id: str, site_id: str, delivery_id: str, **_: Any) -> dict[str, Any]:
    """FR-BRF-05: send through the MailPort; transient failures retry, the attempt and error are recorded."""
    from sqlalchemy import update

    from app.domain.notifications.models import EmailDelivery
    from app.domain.notifications.service import send_delivery

    org, site = uuid.UUID(organisation_id), uuid.UUID(site_id)
    try:
        async with tenant_unit_of_work(org, site) as session:
            ctx = await build_site_context(session, org, site, actor="system:mail")
            return await send_delivery(ctx, uuid.UUID(delivery_id))
    except Exception as exc:
        async with tenant_unit_of_work(org, site) as session:
            await session.execute(update(EmailDelivery).where(EmailDelivery.id == uuid.UUID(delivery_id)).values(
                attempts=EmailDelivery.attempts + 1, last_error=str(exc)[:2000]))
        raise


@site_task("outcomes.evaluate", retry=2)
async def outcomes_evaluate(*, organisation_id: str, site_id: str, business_date: str | None = None,
                            **_: Any) -> dict[str, Any]:
    """FR-ACT-07: measure recommendations whose follow-up date has passed; write memory (FR-MEM-01)."""
    from app.domain.outcomes.evaluator import evaluate_due

    org, site = uuid.UUID(organisation_id), uuid.UUID(site_id)
    async with tenant_unit_of_work(org, site) as session:
        ctx = await build_site_context(session, org, site, actor="system:outcomes")
        day = date.fromisoformat(business_date) if business_date else await ctx.today()
        return await evaluate_due(ctx, day)


@site_task("followups.run", retry=2)
async def followups_run(*, organisation_id: str, site_id: str, business_date: str | None = None,
                        **_: Any) -> dict[str, Any]:
    """16:00: expire overdue proposals and nudge pending approvals (FR-ACT-10)."""
    from app.domain.actions.followups import run_followups

    org, site = uuid.UUID(organisation_id), uuid.UUID(site_id)
    async with tenant_unit_of_work(org, site) as session:
        ctx = await build_site_context(session, org, site, actor="system:followups")
        return await run_followups(ctx)


@site_task("brief.daily", retry=2)
async def brief_daily(*, organisation_id: str, site_id: str, business_date: str | None = None,
                      **_: Any) -> dict[str, Any]:
    """07:00 morning brief for the previous trading day (FR-BRF)."""
    from app.domain.notifications.briefs import send_daily_brief

    org, site = uuid.UUID(organisation_id), uuid.UUID(site_id)
    async with tenant_unit_of_work(org, site) as session:
        ctx = await build_site_context(session, org, site, actor="system:brief")
        day = date.fromisoformat(business_date) if business_date else await ctx.today()
        return {"delivery_id": str(await send_daily_brief(ctx, day) or "")}


@site_task("brief.weekly", retry=2)
async def brief_weekly(*, organisation_id: str, site_id: str, business_date: str | None = None,
                       **_: Any) -> dict[str, Any]:
    """Weekly recap on the configured weekday, covering the seven days ending on `business_date`."""
    from app.domain.notifications.briefs import send_weekly_recap

    org, site = uuid.UUID(organisation_id), uuid.UUID(site_id)
    async with tenant_unit_of_work(org, site) as session:
        ctx = await build_site_context(session, org, site, actor="system:brief")
        day = date.fromisoformat(business_date) if business_date else await ctx.today()
        return {"delivery_id": str(await send_weekly_recap(ctx, day) or "")}
