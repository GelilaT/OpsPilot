"""The Copper Pot demo, step by step, idempotent so Flow 2/3/4 tests can share one database:

1. INV-4471 uploaded, approved by the GM and posted (S1 +18% chicken, S2 12 of 20 kg).
2. Friday 2 Oct simulated with S2; the simulated day's jobs (nightly pipeline, outcomes, follow-ups) run.
"""

import uuid
from datetime import date

from sqlalchemy import select

from app.core.tenancy.scoping import tenant_unit_of_work
from app.domain.actions.models import OperationsCase, Recommendation
from app.domain.intelligence.models import Anomaly, Investigation
from app.simulation.catalogue import Catalogue
from app.simulation.profiles import COPPER_POT
from tests.integration.test_foundations import run_worker_until_idle
from tests.integration.test_step3_invoices import DEMO, detail, run_worker, upload

FRIDAY = date(2026, 10, 2)


async def post_inv_4471(client, copper) -> None:
    listed = (await client.get("/api/v1/invoices", headers=copper["gm"], params={"limit": 200})).json()
    items = listed.get("items", listed) if isinstance(listed, dict) else listed
    if any(i.get("invoice_number") == "INV-4471" and i.get("state") == "posted" for i in items):
        return
    doc = await upload(client, copper["chef"], DEMO / "copper-pot" / "INV-4471.pdf")
    await run_worker()
    d = await detail(client, copper["chef"], doc["document"]["id"])
    if d["document"]["state"] == "ready_for_approval":
        r = await client.post(f"/api/v1/invoices/{doc['document']['id']}/approve", headers=copper["gm"])
        assert r.status_code == 200, r.text
        await run_worker()
    assert (await detail(client, copper["gm"], doc["document"]["id"]))["document"]["state"] in ("posted", "duplicate")


async def business_date(client, copper) -> date:
    return date.fromisoformat((await client.get("/api/v1/simulator/state", headers=copper["gm"])).json()["business_date"])


async def simulate_day(client, copper, scenario: str | None = None) -> dict:
    r = await client.post("/api/v1/simulator/next-day", headers=copper["owner"], json={"scenario": scenario} if scenario
                          else {})
    assert r.status_code == 202, r.text
    await run_worker_until_idle()
    run = (await client.get(f"/api/v1/jobs/runs/{r.json()['id']}", headers=copper["owner"])).json()
    assert run["status"] == "succeeded", run.get("error")
    return run


async def demo_friday(client, copper) -> dict:
    """INV-4471 posted, then Friday simulated; returns the Friday case, its anomaly and investigation."""
    if await business_date(client, copper) < FRIDAY:
        await post_inv_4471(client, copper)
        await simulate_day(client, copper, "S2")
    return await friday_case(copper)


async def friday_case(copper) -> dict:
    cat = Catalogue(COPPER_POT)
    async with tenant_unit_of_work(cat.org_id, uuid.UUID(copper["site"])) as s:
        root = (await s.execute(select(Anomaly).where(
            Anomaly.site_id == uuid.UUID(copper["site"]), Anomaly.period_end == FRIDAY, Anomaly.parent_id.is_(None),
            Anomaly.detector.in_(("revenue_day", "daypart_revenue"))).order_by(
            Anomaly.weekly_impact_minor.desc()).limit(1))).scalar_one()
        case = (await s.execute(select(OperationsCase).where(OperationsCase.anomaly_id == root.id))).scalar_one()
        inv = (await s.execute(select(Investigation).where(Investigation.id == case.investigation_id))).scalar_one()
        recs = (await s.execute(select(Recommendation).where(Recommendation.case_id == case.id))).scalars().all()
    return {"anomaly_id": str(root.id), "detector": root.detector, "case_id": str(case.id),
            "investigation_id": str(inv.id), "recs": {r.type: str(r.id) for r in recs if r.status != "superseded"}}


async def action(client, copper, rec_type: str) -> dict:
    case = await friday_case(copper)
    return (await client.get(f"/api/v1/actions/{case['recs'][rec_type]}", headers=copper["gm"])).json()


async def approve(client, copper, rec_type: str) -> dict:
    """Approve once (idempotent across tests) and let the worker execute it."""
    rec = await action(client, copper, rec_type)
    if rec["status"] == "proposed":
        r = await client.post(f"/api/v1/actions/{rec['id']}/approve", headers={**copper["gm"], "If-Match": str(rec["version"])})
        assert r.status_code == 200, r.text
        await run_worker_until_idle()
    return await action(client, copper, rec_type)
