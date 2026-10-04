"""Operational memory and manager notes (FR-MEM-02/03), and the agent's task list (FR-ACT-05 tasks)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import site_context
from app.core.audit import record_audit
from app.core.errors import NotFound
from app.core.security import Role
from app.core.tenancy.context import SiteContext
from app.domain.actions.models import OperationsCase, OpsTask, Recommendation
from app.domain.actions.service import add_event
from app.domain.intelligence.models import Investigation
from app.domain.memory.models import Note
from app.domain.memory.service import refresh_notes, retrieve

router = APIRouter(tags=["memory"])
Reader = Annotated[SiteContext, Depends(site_context(Role.shift_manager))]


class RecallOut(BaseModel):
    memory_id: str
    case_id: str | None
    date: str
    cause_code: str | None
    summary: str
    verdict: str | None
    score: float
    entity_overlap: float
    cosine: float
    recency: float


@router.get("/memory/search", response_model=list[RecallOut])
async def search(ctx: Reader, q: str = Query("", max_length=400), subject: list[str] = Query(default=[]),
                 cause_code: str | None = None, on: date | None = None):
    """Structured candidates (subject or cause) scored 0.5 entity + 0.3 cosine + 0.2 recency; top 3 >= 0.5."""
    recalls = await retrieve(ctx, subjects=set(subject), cause_code=cause_code, query_text=q or " ".join(subject),
                             on=on or await ctx.today())
    return [RecallOut(**r.as_facts()) for r in recalls]


class NoteIn(BaseModel):
    target_type: Literal["investigation", "recommendation", "case"]
    target_id: uuid.UUID
    text: str = Field(min_length=2, max_length=4000)


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    case_id: uuid.UUID | None
    author: str
    text: str
    created_at: datetime


@router.post("/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def add_note(body: NoteIn, ctx: Reader):
    """FR-MEM-02: a manager's note on an investigation, recommendation or case joins the case memory."""
    case_id: uuid.UUID | None
    if body.target_type == "case":
        case_id = (await ctx.session.execute(select(OperationsCase.id).where(
            OperationsCase.id == body.target_id, OperationsCase.site_id == ctx.site_id))).scalar_one_or_none()
    elif body.target_type == "recommendation":
        case_id = (await ctx.session.execute(select(Recommendation.case_id).where(
            Recommendation.id == body.target_id, Recommendation.site_id == ctx.site_id))).scalar_one_or_none()
    else:
        inv = (await ctx.session.execute(select(Investigation).where(
            Investigation.id == body.target_id, Investigation.site_id == ctx.site_id))).scalar_one_or_none()
        case_id = (await ctx.session.execute(select(OperationsCase.id).where(
            OperationsCase.anomaly_id == inv.anomaly_id))).scalar_one_or_none() if inv else None
        if inv is None:
            raise NotFound("Investigation not found.", code="target_not_found")
    if case_id is None and body.target_type != "investigation":
        raise NotFound("Target not found.", code="target_not_found")
    note = Note(organisation_id=ctx.organisation_id, site_id=ctx.site_id, target_type=body.target_type,
                target_id=body.target_id, case_id=case_id, author=ctx.actor, text=body.text)
    ctx.session.add(note)
    await ctx.session.flush()
    record_audit(ctx.session, actor=ctx.actor, entity_type="note", entity_id=note.id, action="create",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                 after={"target_type": body.target_type, "target_id": str(body.target_id)})
    if case_id:
        add_event(ctx, case_id, "note", f"Note: {body.text[:200]}", {"type": "note", "id": str(note.id)})
        await refresh_notes(ctx, case_id)
    return note


@router.get("/notes", response_model=list[NoteOut])
async def list_notes(ctx: Reader, target_id: uuid.UUID):
    rows = (await ctx.session.execute(select(Note).where(Note.site_id == ctx.site_id, Note.target_id == target_id)
                                      .order_by(Note.created_at))).scalars().all()
    return list(rows)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    recommendation_id: uuid.UUID | None
    title: str
    description: str
    status: str
    assignee_role: str
    due_on: date | None
    closed_note: str | None
    created_at: datetime


class CloseTaskIn(BaseModel):
    note: str = Field(min_length=2, max_length=2000)


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(ctx: Reader, status_filter: str | None = Query(None, alias="status")):
    q = select(OpsTask).where(OpsTask.site_id == ctx.site_id)
    if status_filter:
        q = q.where(OpsTask.status == status_filter)
    return list((await ctx.session.execute(q.order_by(OpsTask.created_at.desc()))).scalars().all())


@router.post("/tasks/{task_id}/close", response_model=TaskOut)
async def close_task(task_id: uuid.UUID, body: CloseTaskIn, ctx: Reader):
    task = (await ctx.session.execute(select(OpsTask).where(
        OpsTask.id == task_id, OpsTask.site_id == ctx.site_id).with_for_update())).scalar_one_or_none()
    if task is None:
        raise NotFound("Task not found.", code="task_not_found")
    before: dict[str, Any] = {"status": task.status}
    task.status, task.closed_note = "closed", body.note
    record_audit(ctx.session, actor=ctx.actor, entity_type="ops_task", entity_id=task.id, action="close",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id, before=before,
                 after={"status": "closed", "note": body.note[:200]})
    await ctx.session.flush()
    return task
