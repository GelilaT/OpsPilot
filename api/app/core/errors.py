"""RFC 7807 problem+json errors with a stable code and the request id (FR-API-02)."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.core.context import request_id_var

PROBLEM_JSON = "application/problem+json"
log = logging.getLogger("opspilot.errors")


class AppError(Exception):
    """Domain/API error rendered as problem+json. `code` is stable and documented."""

    status: int = 400
    code: str = "bad_request"
    title: str = "Bad request"

    def __init__(self, detail: str | None = None, *, code: str | None = None, status: int | None = None,
                 extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        if code:
            self.code = code
        if status:
            self.status = status
        self.extra = extra or {}


class NotFound(AppError):
    status, code, title = 404, "not_found", "Resource not found"


class Unauthorized(AppError):
    status, code, title = 401, "unauthorized", "Authentication required"


class Forbidden(AppError):
    status, code, title = 403, "forbidden", "Not allowed for your role"


class Conflict(AppError):
    status, code, title = 409, "conflict", "Conflict"


class PreconditionFailed(AppError):
    status, code, title = 412, "precondition_failed", "Stale version"


class PayloadTooLarge(AppError):
    status, code, title = 413, "payload_too_large", "Request body too large"


class Unprocessable(AppError):
    status, code, title = 422, "validation_error", "Validation failed"


def problem(status: int, code: str, title: str, detail: str, **extra: Any) -> JSONResponse:
    body = {
        "type": f"https://opspilot.app/problems/{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "request_id": request_id_var.get(),
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return problem(exc.status, exc.code, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return problem(422, "validation_error", "Validation failed", "One or more fields are invalid.",
                       errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized"}.get(exc.status_code, "http_error")
        return problem(exc.status_code, code, str(exc.detail), str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return problem(500, "internal_error", "Internal server error",
                       "Something went wrong on our side. Retry, and quote the request id if it persists.")
