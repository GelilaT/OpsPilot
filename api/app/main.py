"""App factory: middleware (request id, body limits, idempotency, CORS), error handlers, routers."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import app.models
from app.adapters import register_all
from app.api.deps import build_internal_verifier, build_user_verifier
from app.api.v1 import (
    actions,
    admin,
    anomalies,
    cases,
    dashboard,
    files,
    health,
    internal,
    investigations,
    invoices,
    memory,
    menu,
    notifications,
    procurement,
    purchase_orders,
    simulator,
    suppliers,
    tenancy,
)
from app.api.v1 import settings as settings_api
from app.core.db import dispose_engine
from app.core.errors import install_error_handlers, problem
from app.core.idempotency import IdempotencyMiddleware
from app.core.integrations import registry
from app.core.logging import RequestIdMiddleware, configure_logging
from app.core.security import TokenVerifier
from app.core.settings import Settings, get_settings


class BodyLimitMiddleware:
    """20 MB on upload endpoints, 1 MB elsewhere (SRS 2.3)."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app, self.settings = app, settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_upload = scope["path"].rstrip("/").endswith("/invoices") and scope["method"] == "POST"
        limit = self.settings.max_upload_bytes + 64 * 1024 if is_upload else self.settings.max_body_bytes
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            await problem(413, "payload_too_large", "Request body too large",
                          f"The limit for this endpoint is {limit // (1024 * 1024)} MB.")(scope, receive, send)
            return
        seen = 0

        async def limited() -> Message:
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b""))
            if seen > limit:
                raise ValueError("body too large")
            return message

        await self.app(scope, limited, send)


async def _embedded_worker() -> None:
    """Run the Procrastinate worker in this process (RUN_WORKER=1); restart it if it ever stops."""
    from app.workers.app import app as job_app

    log = logging.getLogger("opspilot.worker")
    while True:
        try:
            log.info("starting embedded job worker")
            async with job_app.open_async():
                await job_app.run_worker_async(install_signal_handlers=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("embedded job worker stopped; restarting in 5s")
        await asyncio.sleep(5)


def create_app(settings: Settings | None = None, *, user_verifier: TokenVerifier | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    register_all(registry, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        worker = asyncio.create_task(_embedded_worker()) if settings.run_worker else None
        yield
        if worker:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        await dispose_engine()

    app = FastAPI(
        title="OpsPilot API",
        version="2.1.0",
        description="AI restaurant operations and margin management platform (OPSPILOT-SRS-002).",
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",
        lifespan=lifespan,
    )
    app.state.user_verifier = user_verifier or build_user_verifier(settings)
    app.state.internal_verifier = build_internal_verifier(settings)
    install_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(tenancy.router)
    v1.include_router(admin.router)
    v1.include_router(settings_api.router)
    v1.include_router(simulator.router)
    v1.include_router(invoices.router)
    v1.include_router(menu.router)
    v1.include_router(suppliers.router)
    v1.include_router(procurement.router)
    v1.include_router(anomalies.router)
    v1.include_router(investigations.router)
    v1.include_router(cases.router)
    v1.include_router(actions.router)
    v1.include_router(purchase_orders.router)
    v1.include_router(memory.router)
    v1.include_router(dashboard.router)
    v1.include_router(notifications.router)
    app.include_router(v1)
    app.include_router(files.router)
    app.include_router(internal.router)
    app.include_router(health.router)

    # Outermost first: request id wraps everything so every log line and problem carries it.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(BodyLimitMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-Id", "Idempotent-Replayed"],
    )
    app.add_middleware(RequestIdMiddleware)
    return app


app = create_app()
