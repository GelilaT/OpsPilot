"""Invoice jobs: the intake pipeline (classify -> extract -> validate/match) and posting.

Retries (FR-INV-17): AI and storage errors are retried 3 times after 2, 8 and 32 seconds, then the
document fails with a reason (manual retry available). A rate limit (Gemini 429 or the local token
bucket) defers the job by 60 s without consuming an attempt, at most 10 times.
"""

import hashlib
import uuid
from typing import Any

from sqlalchemy import select

from app.core.context import job_attempt_var
from app.core.tenancy.context import build_site_context
from app.core.tenancy.scoping import tenant_unit_of_work
from app.domain.purchasing.invoice_models import Invoice, InvoiceDocument
from app.domain.purchasing.invoice_pipeline import (
    SYSTEM_ACTOR,
    ai_slot,
    apply_classification,
    evaluate,
    log_ai_call,
    outcome_of,
    post_invoice,
    save_exceptions,
    store_extraction,
    transition,
)
from app.ports import IntegrationKind
from app.ports.ai import DocumentInput
from app.ports.errors import PortError, RateLimitedError, TransientError
from app.workers.runtime import BackoffRetry, Defer, site_task

RETRY_SCHEDULE = (2, 8, 32)


async def _fail(org: uuid.UUID, site: uuid.UUID, doc_id: uuid.UUID, reason: str) -> dict[str, Any]:
    async with tenant_unit_of_work(org, site) as s:
        doc = (await s.execute(select(InvoiceDocument).where(InvoiceDocument.id == doc_id).with_for_update())).scalar_one()
        if doc.state in ("classifying", "extracting", "validating", "matching", "received"):
            doc.failure_reason = reason[:600]
            await transition(s, doc, "failed", actor=SYSTEM_ACTOR, reason=reason)
    return {"state": "failed", "reason": reason}


@site_task("invoice.process", retry=BackoffRetry(RETRY_SCHEDULE, (TransientError,)))
async def process(*, organisation_id: str, site_id: str, document_id: str, **_: Any) -> dict[str, Any]:
    org, site, doc_id = uuid.UUID(organisation_id), uuid.UUID(site_id), uuid.UUID(document_id)
    for _step in range(6):
        async with tenant_unit_of_work(org, site) as s:
            ctx = await build_site_context(s, org, site, actor=SYSTEM_ACTOR)
            doc = (await s.execute(select(InvoiceDocument).where(InvoiceDocument.id == doc_id).with_for_update())
                   ).scalar_one_or_none()
            if doc is None:
                return {"state": "missing"}
            state = doc.state
            if state == "received":
                doc.attempts += 1
                await transition(s, doc, "classifying", actor=SYSTEM_ACTOR, reason="Classifying the document.")
                continue
            if state in ("validating", "matching"):  # resumed after an interruption
                invoice = (await s.execute(select(Invoice).where(Invoice.document_id == doc.id))).scalar_one()
                await evaluate(ctx, doc, invoice, actor=SYSTEM_ACTOR, reason="Validation resumed.")
                return {"state": doc.state}
            if state not in ("classifying", "extracting"):
                return {"state": state}
            if state == "extracting" and doc.extraction is not None:
                await store_extraction(ctx, doc, None, actor=SYSTEM_ACTOR)  # type: ignore[arg-type]
                return {"state": doc.state}
            storage = await ctx.adapter(IntegrationKind.storage)
            ai = await ctx.adapter(IntegrationKind.ai)
            key, mime, sha, pages = doc.storage_key, doc.mime, doc.sha256, doc.pages or 1
            try:
                await ai_slot(ctx, ai)
            except RateLimitedError as exc:
                raise Defer(exc.retry_after, str(exc)) from exc

        # Outside any transaction: fetch the original and call the model.
        purpose = "classify" if state == "classifying" else "extract"
        try:
            content = await storage.get(key)
            if hashlib.sha256(content).hexdigest() != sha:
                return await _fail(org, site, doc_id, "The stored file does not match its SHA-256.")
            document = DocumentInput(content, mime, sha, pages)
            result, info = await (ai.classify(document) if purpose == "classify" else ai.extract(document))
        except PortError as exc:
            async with tenant_unit_of_work(org, site) as s:
                ctx = await build_site_context(s, org, site, actor=SYSTEM_ACTOR)
                doc = await s.get(InvoiceDocument, doc_id)
                assert doc is not None
                log_ai_call(ctx, doc, purpose, ai, None, outcome_of(exc), str(exc))
            if isinstance(exc, RateLimitedError):
                raise Defer(exc.retry_after, str(exc)) from exc
            if isinstance(exc, TransientError) and job_attempt_var.get() < len(RETRY_SCHEDULE):
                raise
            return await _fail(org, site, doc_id, f"{purpose.title()} failed: {exc}")

        async with tenant_unit_of_work(org, site) as s:
            ctx = await build_site_context(s, org, site, actor=SYSTEM_ACTOR)
            doc = (await s.execute(select(InvoiceDocument).where(InvoiceDocument.id == doc_id).with_for_update())).scalar_one()
            log_ai_call(ctx, doc, purpose, ai, info, "ok")
            if doc.state != state:
                return {"state": doc.state, "note": "state changed while the model was running"}
            if purpose == "classify":
                target, reason, issue = apply_classification(ctx, doc, result)  # type: ignore[arg-type]
                await transition(s, doc, target, actor=SYSTEM_ACTOR, reason=reason)
                if issue is not None:
                    await save_exceptions(s, doc, None, [issue], {})
                if target != "extracting":
                    return {"state": target, "document_type": doc.doc_type}
            else:
                await store_extraction(ctx, doc, result, actor=SYSTEM_ACTOR)  # type: ignore[arg-type]
                return {"state": doc.state}
    return {"state": "incomplete"}


@site_task("invoice.post", retry=3)
async def post(*, organisation_id: str, site_id: str, document_id: str, **_: Any) -> dict[str, Any]:
    org, site, doc_id = uuid.UUID(organisation_id), uuid.UUID(site_id), uuid.UUID(document_id)
    async with tenant_unit_of_work(org, site) as s:
        ctx = await build_site_context(s, org, site, actor="system:invoice-posting")
        doc = (await s.execute(select(InvoiceDocument).where(InvoiceDocument.id == doc_id).with_for_update())).scalar_one()
        invoice = (await s.execute(select(Invoice).where(Invoice.document_id == doc.id))).scalar_one()
        if doc.state != "approved":
            return {"posted": False, "state": doc.state}
        return await post_invoice(ctx, doc, invoice, actor=invoice.approved_by or "system:invoice-posting")
