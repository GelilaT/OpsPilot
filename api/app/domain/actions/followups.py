"""16:00 follow-ups (FR-ACT-10): expire overdue proposals and nudge the approvers of pending ones."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.tenancy.context import SiteContext
from app.domain.actions.agent import expire_due
from app.domain.actions.models import Recommendation
from app.domain.notifications.email_format import Highlight, Section, render_email
from app.domain.notifications.service import queue_email


async def run_followups(ctx: SiteContext) -> dict[str, Any]:
    expired = await expire_due(ctx)
    now = datetime.now(UTC)
    old = now - timedelta(hours=ctx.config.get("actions.pending_nudge_hours"))
    soon = now + timedelta(hours=ctx.config.get("actions.expiry_warning_hours"))
    pending = (await ctx.session.execute(select(Recommendation).where(
        Recommendation.site_id == ctx.site_id, Recommendation.status == "proposed").order_by(
        Recommendation.expected_impact_minor.desc()))).scalars().all()
    nudge = [r for r in pending if r.created_at < old or (r.expires_at and r.expires_at < soon)]
    recipients = ctx.config.get("notifications.recipients")
    if nudge and recipients:
        today = await ctx.today()
        subject = f"{len(nudge)} OpsPilot approvals waiting at {ctx.site.name}"
        highlights = [Highlight(
            title=str(r.parameters.get("title", r.type)),
            detail=(f"{r.expected_impact_minor / 100:.2f}/week · needs {r.required_role.replace('_', ' ')}"
                    + (f" · expires {r.expires_at.astimezone(ctx.tz):%a %H:%M}" if r.expires_at else "")),
            tone="warning",
        ) for r in nudge]
        text, html = render_email(
            nav_title="Action Centre",
            headline=f"{len(nudge)} approvals waiting",
            intro=f"These recommendations at {ctx.site.name} need a decision in OpsPilot.",
            sections=[Section("Pending recommendations", highlights=highlights)],
        )
        await queue_email(ctx, key=f"followups:{ctx.site_id}:{today.isoformat()}", to=list(recipients),
                          subject=subject, text=text, html=html, ref={"type": "followups"})
    return {"expired": expired, "nudged": len(nudge)}
