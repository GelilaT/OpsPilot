"""Shared job runtime: idempotent execution, JobRun bookkeeping, retries and deferral (FR-JOB-02/03/07).

Every task receives `organisation_id` / `site_id` in its args so dead letters can be scoped to the
tenant and SiteContext can be built for the job.
"""

import functools
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from procrastinate import BaseRetryStrategy, JobContext, RetryDecision
from procrastinate.jobs import Job
from procrastinate.tasks import Task
from sqlalchemy import func, select, text

from app.core.context import job_attempt_var, job_id_var
from app.core.db import get_sessionmaker
from app.core.jobs import JobRun, mark_run
from app.core.tenancy.scoping import tenant_unit_of_work
from app.workers.app import app

log = logging.getLogger("opspilot.jobs")


class Defer(Exception):
    """Raised by a task to re-run later without consuming a retry attempt (e.g. Gemini 429)."""

    def __init__(self, seconds: float, reason: str) -> None:
        super().__init__(reason)
        self.seconds = seconds
        self.reason = reason


class BackoffRetry(BaseRetryStrategy):
    """Explicit back-off schedule, e.g. (2, 8, 32) seconds for AI and storage errors (FR-INV-17)."""

    def __init__(self, schedule: tuple[int, ...], retry_exceptions: tuple[type[BaseException], ...] = ()):
        self.schedule = schedule
        self.retry_exceptions = retry_exceptions

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        if isinstance(exception, Defer):
            return None
        if self.retry_exceptions and not isinstance(exception, self.retry_exceptions):
            return None
        if job.attempts >= len(self.schedule):
            return None
        return RetryDecision(retry_in={"seconds": self.schedule[job.attempts]})


MAX_DEFERRALS = 10

TaskFn = Callable[..., Awaitable[dict[str, Any] | None]]


def site_task(
    name: str,
    *,
    retry: BaseRetryStrategy | int = 3,
    queue: str = "default",
) -> Callable[[TaskFn], Task]:
    """Declare a tenant-scoped job.

    The wrapped coroutine receives keyword args from the job. If `run_id` is present the JobRun row
    is moved through running -> succeeded/failed. A `Defer` re-enqueues the same job later with a
    deferral counter (max 10) instead of failing.
    """

    def decorator(fn: TaskFn) -> Task:
        @app.task(name=name, queue=queue, retry=retry, pass_context=True)
        @functools.wraps(fn)
        async def wrapper(context: JobContext, **kwargs: Any) -> Any:
            job = context.job
            token = job_id_var.set(str(job.id))
            attempt_token = job_attempt_var.set(job.attempts)
            run_id = uuid.UUID(kwargs["run_id"]) if kwargs.get("run_id") else None
            org = uuid.UUID(kwargs["organisation_id"])

            def unit_of_work():
                return tenant_unit_of_work(org)

            try:
                if run_id:
                    async with unit_of_work() as s:
                        await mark_run(s, run_id, "running")
                try:
                    result = await fn(**kwargs)
                except Defer as d:
                    deferrals = int(kwargs.get("_deferrals", 0)) + 1
                    if deferrals > MAX_DEFERRALS:
                        raise RuntimeError(f"deferred too many times: {d.reason}") from d
                    log.info("job deferred", extra={"task": name, "seconds": d.seconds, "reason": d.reason})
                    async with unit_of_work() as s:
                        if run_id:
                            await mark_run(s, run_id, "deferred", error=d.reason)
                    await app.configure_task(
                        name, schedule_in={"seconds": int(d.seconds) or 1}, queue=queue,
                        lock=job.lock,
                    ).defer_async(**{**kwargs, "_deferrals": deferrals})
                    return {"deferred": d.seconds}
                if run_id:
                    async with unit_of_work() as s:
                        await mark_run(s, run_id, "succeeded", result=result or {}, error=None)
                return result
            except Exception as exc:
                final = _is_final_attempt(wrapper, job, exc)
                if run_id:
                    async with unit_of_work() as s:
                        await mark_run(s, run_id, "failed" if final else "queued", error=str(exc)[:2000])
                log.warning("job error", extra={"task": name, "attempt": job.attempts, "final": final},
                            exc_info=True)
                raise
            finally:
                job_id_var.reset(token)
                job_attempt_var.reset(attempt_token)

        return wrapper

    return decorator


def _is_final_attempt(task: Task, job: Job, exc: BaseException) -> bool:
    strategy = task.retry_strategy
    if strategy is None:
        return True
    return strategy.get_retry_exception(exception=exc, job=job) is None


async def dead_letters(organisation_id: uuid.UUID, limit: int = 100) -> list[dict[str, Any]]:
    """Failed jobs for one organisation (FR-JOB-03)."""
    async with get_sessionmaker()() as s:
        rows = (await s.execute(text(
            "SELECT j.id, j.task_name, j.args, j.attempts, j.queue_name, "
            "  (SELECT max(at) FROM procrastinate_events e WHERE e.job_id = j.id) AS failed_at "
            "FROM procrastinate_jobs j WHERE j.status = 'failed' AND j.args->>'organisation_id' = :org "
            "ORDER BY j.id DESC LIMIT :limit"
        ), {"org": str(organisation_id), "limit": limit})).mappings().all()
    return [dict(r) for r in rows]


async def job_run_for(organisation_id: uuid.UUID, run_id: uuid.UUID) -> JobRun | None:
    async with tenant_unit_of_work(organisation_id) as s:
        return (await s.execute(select(JobRun).where(JobRun.id == run_id))).scalar_one_or_none()


def utc_in(seconds: float) -> Any:
    return func.now() + timedelta(seconds=seconds)
