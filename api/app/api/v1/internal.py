"""/internal/* - scheduler, worker and web-server entry points (FR-AUTH-05).

Not part of the public /api/v1 surface; authenticated by Google OIDC service-account tokens or the
X-Cron-Secret fallback.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import ServiceCaller, SystemSession, require_internal
from app.core.jobs import enqueue, job_key
from app.core.schedules import SCHEDULED_JOBS
from app.core.schedules import dispatch as run_dispatch
from app.core.tenancy.services import claims_for_user

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


class DispatchIn(BaseModel):
    """Empty body: run the scheduler tick. With a site: enqueue one job for it now (operator / tests)."""

    organisation_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    task: str = "nightly.pipeline"
    business_date: date | None = None
    include_simulated: bool = False


@router.get("/auth/claims/{user_id}")
async def auth_claims(user_id: str, session: SystemSession,
                      _: Annotated[ServiceCaller, Depends(require_internal)]) -> dict:
    """Organisation and site-role claims that Better Auth embeds in the user's JWT (FR-AUTH-02)."""
    return await claims_for_user(session, user_id)


@router.post("/dispatch")
async def dispatch(session: SystemSession, _: Annotated[ServiceCaller, Depends(require_internal)],
                   body: DispatchIn | None = None) -> dict:
    """FR-JOB-05: every 5 minutes compute due schedules per site timezone (pipeline 02:00, outcomes 06:00,
    follow-ups 16:00) and enqueue each once per site, date and job."""
    body = body or DispatchIn()
    if body.site_id is None or body.organisation_id is None:
        queued = await run_dispatch(session, datetime.now(UTC), include_simulated=body.include_simulated)
        return {"queued": queued}
    if body.task not in SCHEDULED_JOBS:
        return {"queued": [], "reason": "unsupported task"}
    day = body.business_date.isoformat() if body.business_date else None
    args = {"organisation_id": str(body.organisation_id), "site_id": str(body.site_id)}
    if day:
        args["business_date"] = day
    job_id = await enqueue(session, body.task, key=job_key(body.task, body.site_id, day or "today"),
                           lock=f"site:{body.site_id}", args=args)
    return {"queued": [{"site_id": str(body.site_id), "job": body.task, "job_id": job_id}] if job_id else []}
