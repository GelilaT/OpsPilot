"""Nightly site pipeline (FR-STK-03, FR-MNU-02, FR-ANO-01..05, FR-RCA, FR-ACT-11/12).

theoretical consumption -> item cost snapshots -> detectors -> investigations -> cases and proposals.

One incident, one case: a site-level revenue anomaly is investigated first and the same day's related
anomalies (daypart drops, the stock-out, and any anomaly on an entity the investigation implicated, such as
the ingredient's price increase or the dish's margin decline) are folded into it as evidence instead of
opening cases of their own.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, time
from typing import Any

from app.core.tenancy.context import SiteContext
from app.domain.actions.agent import expire_due, run_after_investigation
from app.domain.detectors.engine import Saved, investigable, run_detectors
from app.domain.intelligence.models import Anomaly
from app.domain.inventory.services import post_theoretical_consumption
from app.domain.investigation.engine import investigate
from app.domain.menu.margin_engine import snapshot_site_day

log = logging.getLogger("opspilot.pipeline")

PRIORITY = ["revenue_day", "daypart_revenue", "stock_out", "margin_decline", "price_increase", "item_cost_increase",
            "supplier_fill_rate", "cogs_drift", "labour_over_target", "discount_spike", "void_spike", "cash_variance",
            "product_decline", "item_food_cost_high"]
_REVENUE_CHILDREN = {"daypart_revenue", "stock_out", "product_decline", "labour_over_target", "cogs_drift"}
SAME_DAY_CHILDREN = {"revenue_day": _REVENUE_CHILDREN, "daypart_revenue": _REVENUE_CHILDREN}


@dataclass
class PipelineResult:
    business_date: str
    theoretical_consumption_rows: int = 0
    cost_snapshots: int = 0
    anomalies: int = 0
    new_anomalies: int = 0
    investigations: int = 0
    cases: list[str] = field(default_factory=list)
    folded: int = 0
    expired: int = 0
    skipped_detectors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _key(a: Anomaly) -> str:
    return f"{a.subject.get('type')}:{a.subject.get('id')}"


async def run_nightly(ctx: SiteContext, day: date) -> PipelineResult:
    out = PipelineResult(day.isoformat())
    close = ctx.local(day, time(23, 50)).astimezone(UTC)
    out.theoretical_consumption_rows = await post_theoretical_consumption(ctx, day, close)
    out.cost_snapshots = await snapshot_site_day(ctx, day)
    saved = await run_detectors(ctx, day)
    out.anomalies, out.new_anomalies = len(saved), sum(1 for s in saved if s.new)
    rank = {d: i for i, d in enumerate(PRIORITY)}
    queue: list[Saved] = sorted(saved, key=lambda s: (rank.get(s.anomaly.detector, 99), -s.anomaly.weekly_impact_minor))
    for s in queue:
        root = s.anomaly
        if not investigable(s) or root.parent_id is not None:
            continue
        children = [c.anomaly for c in queue if c.anomaly is not root and c.anomaly.parent_id is None
                    and c.anomaly.detector in SAME_DAY_CHILDREN.get(root.detector, set())
                    and c.anomaly.period_end == root.period_end]
        for child in children:
            child.parent_id = root.id
        inv = await investigate(ctx, root, related=children)
        out.investigations += 1
        implicated = set(inv.graph.get("entities", []))
        for other in queue:
            a = other.anomaly
            if a is root or a.parent_id is not None or a.investigated_severity is not None:
                continue
            if _key(a) in implicated:
                a.parent_id = root.id
                children.append(a)
        if children:
            inv.graph = {**inv.graph, "related_anomalies": [str(a.id) for a in children]}
        out.folded += len(children)
        case = await run_after_investigation(ctx, root, inv)
        out.cases.append(str(case.id))
    out.expired = await expire_due(ctx)
    log.info("nightly pipeline", extra=out.as_dict())
    return out
