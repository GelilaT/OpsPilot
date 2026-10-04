"""Emails through the MailPort with retries and recorded delivery status (FR-BRF-05).

`queue_email` records an EmailDelivery (pending) and enqueues `email.send` in the caller's transaction,
so an email exists only if the state change that caused it commits. The job sends through the site's
MailPort; transient failures and rate limits are retried by the job engine, permanent ones are recorded.
A delivery is idempotent on its key: queueing the same key twice sends once.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.jobs import enqueue, job_key
from app.core.tenancy.context import SiteContext
from app.domain.notifications.models import EmailDelivery
from app.ports import IntegrationKind
from app.ports.errors import PermanentError
from app.ports.mail import EmailMessage

MAX_ATTEMPTS = 4


async def queue_email(ctx: SiteContext, *, key: str, to: list[str], subject: str, text: str,
                      html: str | None = None, ref: dict[str, Any] | None = None,
                      related_id: uuid.UUID | None = None) -> uuid.UUID | None:
    if not to:
        return None
    payload_ref = dict(ref or {})
    html_stored = html[:50000] if html else None
    if html_stored:
        payload_ref["html"] = html_stored
    row_id = uuid.uuid4()
    inserted = (await ctx.session.execute(insert(EmailDelivery).values(
        id=row_id, organisation_id=ctx.organisation_id, site_id=ctx.site_id, idempotency_key=key, to=to,
        subject=subject[:300], text=text[:20000], html_body=html_stored, status="pending", attempts=0,
        ref=payload_ref, related_id=related_id,
    ).on_conflict_do_nothing(index_elements=["idempotency_key"]).returning(EmailDelivery.id))).scalar_one_or_none()
    if inserted is None:
        return (await ctx.session.execute(select(EmailDelivery.id).where(
            EmailDelivery.idempotency_key == key))).scalar_one()
    await enqueue(ctx.session, "email.send", key=job_key("email.send", inserted), lock=f"email:{inserted}",
                  args={"organisation_id": str(ctx.organisation_id), "site_id": str(ctx.site_id),
                        "delivery_id": str(inserted)})
    return inserted


async def send_delivery(ctx: SiteContext, delivery_id: uuid.UUID) -> dict[str, Any]:
    d = (await ctx.session.execute(select(EmailDelivery).where(
        EmailDelivery.id == delivery_id).with_for_update())).scalar_one()
    if d.status in ("accepted", "sent", "logged"):
        return {"status": d.status, "replayed": True}
    d.attempts += 1
    mail = await ctx.adapter(IntegrationKind.mail)
    try:
        body_html = d.html_body or (d.ref or {}).get("html")
        result = await mail.send(EmailMessage(to=tuple(d.to), subject=d.subject, text=d.text, html=body_html,
                                              idempotency_key=d.idempotency_key,
                                              tags=(str((d.ref or {}).get("type", "ops")),)))
    except PermanentError as exc:
        d.status, d.last_error = "failed", str(exc)[:2000]
        return {"status": "failed", "error": d.last_error}
    except Exception as exc:
        d.last_error = str(exc)[:2000]
        if d.attempts >= MAX_ATTEMPTS:
            d.status = "failed"
            return {"status": "failed", "error": d.last_error}
        raise
    d.status, d.provider, d.provider_message_id = result.status, result.provider, result.provider_message_id
    d.sent_at, d.last_error = datetime.now(UTC), None
    return {"status": d.status, "provider": d.provider}
