"""Administration: audit log (FR-SET-03), job runs (FR-API-07), dead letters and retry (FR-JOB-03)."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select, text

from app.api.deps import Session, SiteScope, require_org_role, site_scope
from app.core.audit import AuditEvent, record_audit
from app.core.errors import NotFound, Unprocessable
from app.core.jobs import JobRun, enqueue, job_key
from app.core.security import Principal, Role
from app.core.tenancy.models import OrganisationUser
from app.core.tenancy.services import actor_label, actor_names
from app.workers.runtime import dead_letters
from app.workers.tasks import USER_RUNNABLE

router = APIRouter(tags=["administration"])


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    site_id: uuid.UUID | None
    actor: str
    actor_name: str | None = None
    entity_type: str
    entity_id: str
    action: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None
    job_id: str | None


class AuditPage(BaseModel):
    items: list[AuditOut]
    next_cursor: str | None


@router.get("/audit", response_model=AuditPage)
async def audit_log(
    session: Session,
    principal: Annotated[Principal, Depends(require_org_role(Role.owner))],
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor: str | None = None,
    site_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    q = select(AuditEvent).where(AuditEvent.organisation_id == principal.organisation_id)
    if entity_type:
        term = entity_type.strip()
        q = q.where(or_(
            AuditEvent.entity_type.ilike(f"%{term}%"),
            AuditEvent.action.ilike(f"%{term}%"),
        ))
    if entity_id:
        q = q.where(AuditEvent.entity_id.ilike(f"%{entity_id.strip()}%"))
    if actor:
        term = actor.strip()
        if term.startswith("user:") or term.startswith("system:") or term == "agent":
            q = q.where(AuditEvent.actor == term)
        else:
            user_ids = (await session.execute(select(OrganisationUser.user_id).where(
                OrganisationUser.organisation_id == principal.organisation_id,
                or_(OrganisationUser.display_name.ilike(f"%{term}%"), OrganisationUser.email.ilike(f"%{term}%")),
            ))).scalars().all()
            actor_match = [AuditEvent.actor.ilike(f"%{term}%")]
            if user_ids:
                actor_match.append(AuditEvent.actor.in_([f"user:{u}" for u in user_ids]))
            q = q.where(or_(*actor_match))
    if site_id:
        q = q.where(AuditEvent.site_id == site_id)
    if since:
        q = q.where(AuditEvent.at >= since)
    if until:
        q = q.where(AuditEvent.at < until)
    if cursor:
        try:
            q = q.where(AuditEvent.id < int(cursor))
        except ValueError as exc:
            raise Unprocessable("Invalid cursor.", code="invalid_cursor") from exc
    rows = list((await session.execute(q.order_by(AuditEvent.id.desc()).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    names = await actor_names(session, [r.actor for r in rows])
    items = [
        AuditOut.model_validate(r).model_copy(update={"actor_name": actor_label(names, r.actor)})
        for r in rows
    ]
    return AuditPage(items=items, next_cursor=str(rows[-1].id) if more and rows else None)


class JobRunIn(BaseModel):
    task: str
    payload: dict[str, Any] = Field(default_factory=dict)


class JobRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task: str
    status: str
    attempts: int
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@router.post("/jobs/runs", response_model=JobRunOut, status_code=status.HTTP_202_ACCEPTED)
async def start_job(body: JobRunIn, session: Session,
                    scope: Annotated[SiteScope, Depends(site_scope(Role.general_manager))]):
    """Start a long-running operation; poll GET /jobs/runs/{id} for its state (FR-API-07)."""
    if body.task not in USER_RUNNABLE:
        raise Unprocessable(f"Unknown task {body.task!r}.", code="unknown_task")
    run = JobRun(id=uuid.uuid4(), organisation_id=scope.organisation_id, site_id=scope.site_id, task=body.task,
                 idempotency_key="", payload=body.payload, requested_by=scope.actor, status="queued", attempts=0)
    run.idempotency_key = job_key(body.task, run.id)
    session.add(run)
    await session.flush()
    run.procrastinate_job_id = await enqueue(
        session, body.task, key=run.idempotency_key,
        args={"organisation_id": str(scope.organisation_id), "site_id": str(scope.site_id),
              "run_id": str(run.id), "payload": body.payload},
    )
    record_audit(session, actor=scope.actor, entity_type="job_run", entity_id=run.id, action="enqueue",
                 organisation_id=scope.organisation_id, site_id=scope.site_id,
                 after={"task": body.task, "payload": body.payload})
    await session.flush()
    await session.refresh(run)
    return JobRunOut.model_validate(run)


@router.get("/jobs/runs/{run_id}", response_model=JobRunOut)
async def get_job_run(run_id: uuid.UUID, session: Session,
                      scope: Annotated[SiteScope, Depends(site_scope(Role.shift_manager))]):
    run = await session.get(JobRun, run_id)
    if run is None or run.organisation_id != scope.organisation_id or run.site_id != scope.site_id:
        raise NotFound("Job run not found.")
    return JobRunOut.model_validate(run)


class DeadLetterOut(BaseModel):
    id: int
    task_name: str
    args: dict[str, Any]
    attempts: int
    queue_name: str
    failed_at: datetime | None


@router.get("/jobs/dead-letter", response_model=list[DeadLetterOut])
async def list_dead_letters(principal: Annotated[Principal, Depends(require_org_role(Role.owner))]):
    assert principal.organisation_id
    return [DeadLetterOut(**r) for r in await dead_letters(principal.organisation_id)]


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(job_id: int, session: Session,
                    principal: Annotated[Principal, Depends(require_org_role(Role.owner))]):
    row = (await session.execute(text(
        "SELECT id, task_name, args FROM procrastinate_jobs WHERE id = :id AND status = 'failed' "
        "AND args->>'organisation_id' = :org FOR UPDATE"
    ), {"id": job_id, "org": str(principal.organisation_id)})).mappings().first()
    if row is None:
        raise NotFound("Failed job not found.")
    await session.execute(text("SELECT procrastinate_retry_job_v2(:id, now(), NULL, NULL, NULL)"), {"id": job_id})
    if row["args"].get("run_id"):
        run = await session.get(JobRun, uuid.UUID(row["args"]["run_id"]))
        if run is not None:
            run.status, run.error = "queued", None
    record_audit(session, actor=principal.actor, entity_type="job", entity_id=job_id, action="retry",
                 organisation_id=principal.organisation_id, after={"task": row["task_name"]})
    return {"id": job_id, "status": "todo"}
