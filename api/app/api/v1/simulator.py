"""Simulator controls (FR-ING-02): advance a simulated site by one trading day."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import Session, SiteScope, site_scope
from app.api.v1.admin import JobRunOut
from app.core.audit import record_audit
from app.core.errors import Conflict, Unprocessable
from app.core.jobs import JobRun, enqueue, job_key
from app.core.security import Role
from app.core.tenancy.config import resolve_config
from app.core.tenancy.context import build_site_context
from app.core.tenancy.models import SiteClock
from app.simulation.scenarios import SCENARIO_CATALOGUE
from app.simulation.service import scenarios_on, simulator_target

router = APIRouter(prefix="/simulator", tags=["simulator"])


class SimulatorState(BaseModel):
    enabled: bool
    business_date: date | None
    next_date: date | None
    scenarios: dict[str, str]


class NextDayIn(BaseModel):
    scenario: str | None = None


@router.get("/state", response_model=SimulatorState)
async def state(session: Session, scope: Annotated[SiteScope, Depends(site_scope(Role.shift_manager))]):
    config = await resolve_config(session, scope.organisation_id, scope.site_id)
    clock = (await session.execute(select(SiteClock).where(SiteClock.site_id == scope.site_id))).scalar_one_or_none()
    enabled = bool(config.get("simulation.enabled")) and clock is not None
    return SimulatorState(enabled=enabled, business_date=clock.business_date if clock else None,
                          next_date=date.fromordinal(clock.business_date.toordinal() + 1) if clock else None,
                          scenarios=SCENARIO_CATALOGUE)


@router.post("/next-day", response_model=JobRunOut, status_code=status.HTTP_202_ACCEPTED)
async def next_day(body: NextDayIn, session: Session,
                   scope: Annotated[SiteScope, Depends(site_scope(Role.owner))]):
    """Simulate the next trading day (optionally checking a planted scenario); poll the returned run."""
    clock = (await session.execute(select(SiteClock).where(SiteClock.site_id == scope.site_id))).scalar_one_or_none()
    if clock is None:
        raise Conflict("This site is not running on the simulator.", code="not_simulated")
    target = date.fromordinal(clock.business_date.toordinal() + 1)
    if body.scenario:
        ctx = await build_site_context(session, scope.organisation_id, scope.site_id, actor=scope.actor)
        sim = await simulator_target(ctx)
        planted = scenarios_on(sim.profile.slug, sim.site.code, target)
        if body.scenario not in planted:
            known = body.scenario in SCENARIO_CATALOGUE
            raise Unprocessable(
                (f"Scenario {body.scenario} is not planted on {target.isoformat()}"
                 + (f" (planted today: {', '.join(planted)})." if planted else ".")) if known
                else f"Unknown scenario {body.scenario!r}.", code="scenario_not_available")
    run = JobRun(id=uuid.uuid4(), organisation_id=scope.organisation_id, site_id=scope.site_id,
                 task="simulator.next_day", idempotency_key=job_key("simulator.next_day", scope.site_id, target),
                 payload={"scenario": body.scenario, "business_date": target.isoformat()},
                 requested_by=scope.actor, status="queued", attempts=0)
    session.add(run)
    await session.flush()
    job_id = await enqueue(session, "simulator.next_day", key=run.idempotency_key, lock=f"site:{scope.site_id}",
                           args={"organisation_id": str(scope.organisation_id), "site_id": str(scope.site_id),
                                 "run_id": str(run.id), "scenario": body.scenario, "actor": scope.actor})
    if job_id is None:
        raise Conflict(f"{target.isoformat()} is already being simulated.", code="already_queued")
    run.procrastinate_job_id = job_id
    record_audit(session, actor=scope.actor, entity_type="job_run", entity_id=run.id, action="enqueue",
                 organisation_id=scope.organisation_id, site_id=scope.site_id, after=run.payload)
    await session.flush()
    await session.refresh(run)
    return JobRunOut.model_validate(run)
