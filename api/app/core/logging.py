"""Structured JSON logs with request id and job id (SRS 2.4 Observability)."""

import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import job_id_var, request_id_var


class JsonFormatter(logging.Formatter):
    _reserved = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
            "job_id": job_id_var.get(),
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in self._reserved})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).handlers[:] = []
        logging.getLogger(noisy).propagate = False


class RequestIdMiddleware:
    """Assigns X-Request-Id (or accepts a valid incoming one) and logs one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.log = logging.getLogger("opspilot.http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode()[:64]
        rid = incoming if incoming.replace("-", "").isalnum() and incoming else str(uuid.uuid4())
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            self.log.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)
