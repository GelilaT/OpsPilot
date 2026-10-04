"""Derived history for a seeded site, computed by the real domain code after the raw rows are loaded:

* daily item cost snapshots for every seeded day (FR-MNU-02), so margins and the 28-day detectors have
  history from day one;
* the operational record of scenario S7 - the 19 Sep short delivery from Supplier A and its resolution
  (par level raised on 21 Sep) - as a closed case with its memory entry (FR-MEM-01), built from the
  seeded PO, goods received and audit trail.
"""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select

from app.core.tenancy.context import SiteContext
from app.domain.actions.models import CaseEvent, OperationsCase
from app.domain.detectors.stock_out import find_stock_outs
from app.domain.intelligence.models import Anomaly
from app.domain.inventory.models import Ingredient
from app.domain.investigation.hypotheses import deliveries
from app.domain.memory.service import upsert_entry
from app.domain.menu.margin_engine import snapshot_range
from app.simulation.catalogue import Catalogue
from app.simulation.profile import OrgProfile
from app.simulation.scenarios import PAR_CHANGES, SHORT_DELIVERIES


async def backfill(ctx: SiteContext, profile: OrgProfile, site_code: str, start: date, end: date) -> dict:
    snapshots = await snapshot_range(ctx, start, end)
    remembered = 0
    cat = Catalogue(profile)
    for s in SHORT_DELIVERIES:
        if s.org != profile.slug or s.site != site_code or not (start <= s.on < end):
            continue
        if await remember_short_delivery(ctx, cat, s, profile):
            remembered += 1
    return {"snapshots": snapshots, "memory": remembered}


async def remember_short_delivery(ctx: SiteContext, cat: Catalogue, s, profile: OrgProfile) -> bool:
    ingredient_id = cat.ingredient_ids[s.ingredient]
    supplier_id = cat.supplier_ids[s.supplier]
    rows = [d for d in await deliveries(ctx, s.on, s.on, {ingredient_id}) if d.supplier_id == supplier_id]
    if not rows:
        return False
    d = rows[0]
    baseline = [s.on - timedelta(weeks=i) for i in range(1, 5)]
    events = await find_stock_outs(ctx, s.on, baseline, ingredient_ids={ingredient_id})
    fix = next((p for p in PAR_CHANGES if p.org == profile.slug and p.site == s.site and p.ingredient == s.ingredient
                and p.on > s.on), None)
    ing_name = (await ctx.session.execute(select(Ingredient.name).where(Ingredient.id == ingredient_id))).scalar_one()
    sup_name = d.supplier_name
    kg = 1000
    stock_text = (f" {ing_name} ran out at {events[0].out_at:%H:%M} and dishes using it stopped selling."
                  if events else "")
    resolution = (f" Resolved on {fix.on:%d %b} by raising the {ing_name.lower()} par level from "
                  f"{float(fix_from(profile, fix)) / kg:g} kg to {float(fix.par) / kg:g} kg." if fix else "")
    subject = {"type": "ingredient", "id": str(ingredient_id), "name": ing_name, "code": s.ingredient}
    anomaly = Anomaly(
        organisation_id=ctx.organisation_id, site_id=ctx.site_id, detector="stock_out" if events else "supplier_fill_rate",
        subject=subject, period_start=s.on, period_end=s.on, fingerprint=f"seed-history-{s.on.isoformat()}-{s.ingredient}",
        severity="warning", status="closed",
        facts={"po_number": d.po_number, "ordered_kg": float(d.ordered) / kg, "received_kg": float(d.received) / kg,
               "supplier": sup_name, "out_at": events[0].out_at.strftime("%H:%M") if events else None,
               "source": "seed history (S7)"},
        weekly_impact_minor=0, investigated_severity="warning")
    ctx.session.add(anomaly)
    await ctx.session.flush()
    closed_on = fix.on if fix else s.on + timedelta(days=2)
    case = OperationsCase(organisation_id=ctx.organisation_id, site_id=ctx.site_id, anomaly_id=anomaly.id,
                          status="closed", closed_reason="Resolved by the head chef: par level raised.",
                          closed_at=datetime.combine(closed_on, time(10), tzinfo=ctx.tz).astimezone(UTC))
    ctx.session.add(case)
    await ctx.session.flush()
    at = datetime.combine(s.on, time(23, 55), tzinfo=ctx.tz).astimezone(UTC)
    for kind, summary, when in [
        ("detected", f"{d.po_number} from {sup_name}: {float(d.received) / kg:g} kg of {float(d.ordered) / kg:g} kg "
                     f"{ing_name.lower()} received.{stock_text}", at),
        ("closed", case.closed_reason, case.closed_at),
    ]:
        ctx.session.add(CaseEvent(organisation_id=ctx.organisation_id, site_id=ctx.site_id, case_id=case.id, at=when,
                                  actor="system:history", kind=kind, summary=summary, ref={"type": "anomaly",
                                                                                          "id": str(anomaly.id)}))
    summary = (f"{s.on:%d %b %Y}: Supplier short delivery → ingredient stock-out. {sup_name} delivered "
               f"{float(d.received) / kg:g} kg of {float(d.ordered) / kg:g} kg {ing_name.lower()} on {d.po_number}."
               f"{stock_text}{resolution}")
    await upsert_entry(
        ctx, case_id=case.id, kind="outcome", investigation_id=None,
        subjects=[subject, {"type": "supplier", "id": str(supplier_id), "name": sup_name}],
        cause_code="supplier_short_delivery", summary=summary,
        actions=[{"type": "par_level_change", "title": f"Raise {ing_name.lower()} par", "status": "outcome_measured",
                  "verdict": "improved"}] if fix else [],
        outcome={"verdict": "improved" if fix else None}, occurred_on=s.on, resolved_on=closed_on)
    return True


def fix_from(profile: OrgProfile, fix) -> float:
    return float(profile.par_levels.get(fix.ingredient, 0))
