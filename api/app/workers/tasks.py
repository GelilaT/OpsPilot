"""Task registry. Domain workflows (InvoicePipeline, NightlyPipeline, OutcomeEvaluator) register here."""

import uuid
from datetime import date
from typing import Any

from app.core.audit import record_audit
from app.core.tenancy.scoping import tenant_unit_of_work
from app.workers import invoice_tasks, nightly_tasks  # noqa: F401 - registers domain jobs
from app.workers.runtime import site_task

# Tasks a user may start through POST /api/v1/jobs/runs (others are system-triggered only).
USER_RUNNABLE: set[str] = {"system.echo"}


@site_task("system.echo", retry=2)
async def echo(*, organisation_id: str, site_id: str | None = None, run_id: str | None = None,
               payload: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    """Round-trip probe for the job engine: writes an audit event and returns its payload."""
    payload = payload or {}
    if payload.get("fail"):
        raise RuntimeError("echo asked to fail")
    async with tenant_unit_of_work(uuid.UUID(organisation_id)) as s:
        record_audit(
            s, actor="system:worker", entity_type="job_run", entity_id=run_id or "-", action="echo",
            organisation_id=uuid.UUID(organisation_id), site_id=uuid.UUID(site_id) if site_id else None,
            after=payload,
        )
    return {"echo": payload}


@site_task("simulator.next_day", retry=0)
async def simulator_next_day(*, organisation_id: str, site_id: str, run_id: str | None = None,
                             scenario: str | None = None, actor: str = "system:simulator", **_: Any) -> dict[str, Any]:
    """FR-ING-02: one simulated trading day; the nightly pipeline for that date follows (FR-JOB-05)."""
    from dataclasses import asdict

    from app.core.jobs import enqueue, job_key
    from app.core.tenancy.context import build_site_context
    from app.simulation.service import simulate_next_day

    org_id, site_uuid = uuid.UUID(organisation_id), uuid.UUID(site_id)
    async with tenant_unit_of_work(org_id, site_uuid) as s:
        ctx = await build_site_context(s, org_id, site_uuid, actor=actor)
        summary = await simulate_next_day(ctx, scenario)
        day = summary.business_date
        # The simulated day's schedule, in order on the site lock: 02:00 pipeline, 06:00 outcomes, 07:00 brief
        # (+ the weekly recap on its weekday), 16:00 follow-ups.
        tasks = ["nightly.pipeline", "outcomes.evaluate", "brief.daily"]
        if date.fromisoformat(day).weekday() == ctx.config.get("site.schedules").weekly_recap_weekday:
            tasks.append("brief.weekly")
        for task in (*tasks, "followups.run"):
            await enqueue(s, task, key=job_key(task, site_uuid, day), lock=f"site:{site_uuid}",
                          args={"organisation_id": organisation_id, "site_id": site_id, "business_date": day})
    return asdict(summary)
