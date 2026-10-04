"""Request/job correlation ids carried through logs and audit events."""

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)
job_attempt_var: ContextVar[int] = ContextVar("job_attempt", default=0)  # 0 on the first run
