"""Morning brief (daily) and weekly recap emails (FR-BRF): the previous trading day against the same weekday
baseline, what needs the manager's decision, and the week against the one before. Plain text, sent through
`queue_email` so each is recorded and idempotent on its key."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.core.tenancy.context import SiteContext
from app.domain.actions.models import Recommendation, RecommendationOutcome
from app.domain.detectors.baseline import same_weekdays
from app.domain.detectors.data import DayFacts, load_days
from app.domain.detectors.kpis import Kpi, compute_kpis
from app.domain.intelligence.models import Anomaly
from app.domain.notifications.email_format import Highlight, Metric, RiskItem, Section, render_email
from app.domain.notifications.service import queue_email
from app.domain.purchasing.invoice_models import InvoiceDocument

REVIEW_STATES = ("needs_review", "ready_for_approval", "failed")


def _money(minor: float | int | None, currency: str) -> str:
    return "—" if minor is None else f"{currency} {minor / 100:,.0f}"


def _kpi_metric(k: Kpi, currency: str) -> Metric:
    def fmt(v: float | None) -> str:
        if v is None:
            return "—"
        return _money(v, currency) if k.unit == "money" else f"{v:.1f}%" if k.unit == "pct" else f"{v:,.0f}"

    delta = "n/a" if k.delta is None else f"{k.delta:+.1f}{' pt' if k.delta_unit == 'pt' else '%'}"
    return Metric(label=k.label, value=fmt(k.value), sub=f"{delta} vs {fmt(k.baseline)} usual")


async def _risks(ctx: SiteContext, day: date, limit: int = 5) -> list[Anomaly]:
    return list((await ctx.session.execute(select(Anomaly).where(
        Anomaly.site_id == ctx.site_id, Anomaly.parent_id.is_(None), Anomaly.status.in_(("open", "investigating")),
        Anomaly.period_end >= day - timedelta(days=7), Anomaly.period_end <= day).order_by(
        Anomaly.weekly_impact_minor.desc()).limit(limit))).scalars())


def _risk_items(risks: list[Anomaly], currency: str) -> list[RiskItem]:
    return [RiskItem(
        title=f"{a.detector.replace('_', ' ').title()} · {a.subject.get('name') or a.subject.get('type', '')}",
        impact=f"{_money(a.weekly_impact_minor, currency)} / week estimated impact",
        severity=a.severity,
    ) for a in risks]


async def build_daily_brief(ctx: SiteContext, day: date) -> tuple[str, str, str]:
    cur = ctx.site.currency
    base = same_weekdays(day, ctx.config.get("detection.baseline_weeks"))
    days = await load_days(ctx.session, ctx.site_id, [day, *base])
    kpis = compute_kpis(days[day], [days[d] for d in base])
    pending = (await ctx.session.execute(select(func.count(), func.coalesce(func.sum(
        Recommendation.expected_impact_minor), 0)).where(
        Recommendation.site_id == ctx.site_id, Recommendation.status == "proposed"))).one()
    to_review = (await ctx.session.execute(select(func.count()).where(
        InvoiceDocument.site_id == ctx.site_id, InvoiceDocument.state.in_(REVIEW_STATES)))).scalar_one()
    risks = await _risks(ctx, day)
    outcomes = (await ctx.session.execute(select(RecommendationOutcome, Recommendation).join(
        Recommendation, Recommendation.id == RecommendationOutcome.recommendation_id).where(
        RecommendationOutcome.site_id == ctx.site_id).order_by(
        RecommendationOutcome.created_at.desc()).limit(3))).all()
    intro = (f"Trading day {day:%A %d %B %Y}, compared with the same weekday over the last "
             f"{ctx.config.get('detection.baseline_weeks')} weeks.")
    sections: list[Section] = [
        Section(
            "Key numbers",
            metrics=[_kpi_metric(k, cur) for k in kpis] if days[day].traded else None,
            lines=[] if days[day].traded else ["No trading recorded for this day."],
        ),
        Section("Needs you", highlights=[
            Highlight(
                title=f"{pending[0]} recommendations awaiting approval",
                detail=f"{_money(int(pending[1]), cur)} / week at stake · review in Action Centre",
                tone="warning",
            ),
            Highlight(
                title=f"{to_review} invoices need review",
                detail="Open the Invoice Inbox to approve or fix exceptions.",
                tone="info" if to_review else "neutral",
            ),
        ]),
        Section("Top risks", risks=_risk_items(risks, cur)),
    ]
    if outcomes:
        sections.append(Section("Recent outcomes", lines=[
            f"{r.parameters.get('title', r.type)}: {o.verdict}"
            + (f" ({Decimal(o.effect_pct):+.1f}%)" if o.effect_pct is not None else "")
            for o, r in outcomes
        ]))
    headline = f"Good morning — {ctx.site.name}"
    subject = f"Morning brief — {ctx.site.name}, {day:%a %d %b}"
    text, html = render_email(nav_title="Morning brief", headline=headline, intro=intro, sections=sections)
    return subject, text, html


def _sum(days: list[DayFacts]) -> dict[str, int]:
    rev, cogs = sum(d.revenue for d in days), sum(d.cogs for d in days)
    return {"revenue": rev, "orders": sum(d.orders for d in days), "cogs": cogs,
            "labour": sum(d.labour_cost for d in days)}


def _vs(now: float, before: float) -> str:
    return "n/a" if not before else f"{(now - before) / before * 100:+.1f}%"


async def build_weekly_recap(ctx: SiteContext, week_end: date) -> tuple[str, str, str]:
    cur = ctx.site.currency
    this = [week_end - timedelta(days=i) for i in range(6, -1, -1)]
    prior = [d - timedelta(days=7) for d in this]
    facts = await load_days(ctx.session, ctx.site_id, [*this, *prior])
    a, b = _sum([facts[d] for d in this]), _sum([facts[d] for d in prior])
    gp = lambda s: (s["revenue"] - s["cogs"]) / s["revenue"] * 100 if s["revenue"] else 0.0  # noqa: E731
    lab = lambda s: s["labour"] / s["revenue"] * 100 if s["revenue"] else 0.0  # noqa: E731
    start = datetime.combine(this[0], datetime.min.time(), tzinfo=ctx.tz)
    opened = (await ctx.session.execute(select(func.count()).where(
        Anomaly.site_id == ctx.site_id, Anomaly.parent_id.is_(None), Anomaly.period_end >= this[0],
        Anomaly.period_end <= week_end))).scalar_one()
    measured = (await ctx.session.execute(select(RecommendationOutcome, Recommendation).join(
        Recommendation, Recommendation.id == RecommendationOutcome.recommendation_id).where(
        RecommendationOutcome.site_id == ctx.site_id, RecommendationOutcome.created_at >= start).order_by(
        RecommendationOutcome.created_at.desc()))).all()
    risks = await _risks(ctx, week_end)
    intro = f"{this[0]:%a %d %b} to {week_end:%a %d %b %Y}, compared with the week before."
    sections: list[Section] = [
        Section("The week", metrics=[
            Metric("Revenue", _money(a["revenue"], cur), _vs(a["revenue"], b["revenue"]) + " vs prior week"),
            Metric("Orders", f"{a['orders']:,}", _vs(a["orders"], b["orders"]) + " vs prior week"),
            Metric("GP %", f"{gp(a):.1f}%", f"{gp(a) - gp(b):+.1f} pt vs prior week"),
            Metric("Labour %", f"{lab(a):.1f}%", f"{lab(a) - lab(b):+.1f} pt vs prior week"),
        ]),
        Section("Watch", highlights=[
            Highlight(f"{opened} issues flagged this week", "Review open cases and anomalies in OpsPilot.", tone="info"),
        ], risks=_risk_items(risks, cur)),
    ]
    if measured:
        sections.append(Section("What we acted on", lines=[
            f"{r.parameters.get('title', r.type)}: {o.verdict}" for o, r in measured
        ]))
    headline = f"Weekly recap — {ctx.site.name}"
    subject = f"Weekly recap — {ctx.site.name}, w/e {week_end:%d %b}"
    text, html = render_email(nav_title="Weekly recap", headline=headline, intro=intro, sections=sections)
    return subject, text, html


async def send_daily_brief(ctx: SiteContext, day: date, *, suffix: str = "") -> uuid.UUID | None:
    subject, text, html = await build_daily_brief(ctx, day)
    return await queue_email(ctx, key=f"brief:{ctx.site_id}:{day.isoformat()}{suffix}",
                             to=list(ctx.config.get("notifications.recipients")), subject=subject, text=text, html=html,
                             ref={"type": "daily_brief"})


async def send_weekly_recap(ctx: SiteContext, week_end: date, *, suffix: str = "") -> uuid.UUID | None:
    subject, text, html = await build_weekly_recap(ctx, week_end)
    return await queue_email(ctx, key=f"recap:{ctx.site_id}:{week_end.isoformat()}{suffix}",
                             to=list(ctx.config.get("notifications.recipients")), subject=subject, text=text, html=html,
                             ref={"type": "weekly_recap"})
