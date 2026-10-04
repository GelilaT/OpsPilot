"""Flow 3 (FR-ACT-01..06, 08, 09, 11..13; FR-PRC-07/08/10; FR-BRF-05): the Action Centre.

Exit criterion (plan Step 5): approving the S3 supplier switch creates a draft PO and an emailed commit.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.tenancy.context import build_site_context
from app.core.tenancy.scoping import tenant_unit_of_work
from app.domain.actions.agent import run_execution
from app.domain.actions.models import Recommendation, RecommendationExecution
from app.domain.notifications.models import EmailDelivery
from app.domain.purchasing.models import PurchaseOrder
from app.simulation.catalogue import Catalogue
from app.simulation.profiles import COPPER_POT, NORTHSIDE
from tests.conftest import auth
from tests.integration.scenario import action, approve, demo_friday
from tests.integration.test_step4_flow2 import demo_token, site_id

pytestmark = pytest.mark.integration


async def test_case_and_queue(client, copper):
    """FR-ACT-02/09/11/13: one case awaiting approval, its recommendations priced from data and queued by
    impact x confidence."""
    case = await demo_friday(client, copper)
    h = copper["gm"]
    cases = (await client.get("/api/v1/cases", headers=h)).json()
    friday = next(c for c in cases if c["id"] == case["case_id"])
    assert cases[0]["status"] == "awaiting_approval" and friday["severity"] == "critical"
    assert friday["top_cause"] == "Supplier short delivery → Ingredient stock-out" and friday["pending_approvals"] >= 3

    everything = (await client.get("/api/v1/actions", headers=h, params={"status": "proposed"})).json()
    scores = [a["queue_score"] for a in everything]
    assert scores == sorted(scores, reverse=True)
    queue = (await client.get("/api/v1/actions", headers=h, params={"case_id": case["case_id"]})).json()
    switch = next(a for a in queue if a["type"] == "supplier_switch")
    i = switch["impact_inputs"]
    assert (i["price_from"], i["price_to"], i["fill_rate_pct"]) == (7.9, 7.19, 97.0)
    assert switch["expected_impact_minor"] == round(i["weekly_qty_base"] * i["price_delta_per_base"])
    assert switch["required_role"] == "general_manager" and switch["parameters"]["to_supplier_name"].startswith("Bramley")
    assert switch["follow_up_at"] and switch["expires_at"] and switch["success_metric"] == "cost_per_base_unit"
    review = next(a for a in queue if a["type"] == "price_review")
    assert review["subject"]["name"] == "Chicken Wrap" and review["parameters"]["suggested_gross_minor"] == 995
    assert review["impact_inputs"]["suggested_gp_pct"] == 65.9 and review["required_role"] == "owner"
    par = next(a for a in queue if a["type"] == "par_level_change")
    assert par["impact_inputs"]["par_from"] == 18 and par["impact_inputs"]["par_to"] > 18

    detail = (await client.get(f"/api/v1/actions/{switch['id']}", headers=h)).json()
    assert detail["evidence"] and detail["finding"] and detail["history"][-1]["to_status"] == "proposed"


async def test_rbac_concurrency_and_adjust(client, copper):
    """FR-ACT-03/04: approver roles, If-Match (412), illegal transitions (409), adjust recomputes impact."""
    await demo_friday(client, copper)
    switch = await action(client, copper, "supplier_switch")
    if switch["status"] == "proposed":
        r = await client.post(f"/api/v1/actions/{switch['id']}/approve", headers=copper["chef"])
        assert r.status_code == 403 and r.json()["code"] == "approval_limit"
        r = await client.post(f"/api/v1/actions/{switch['id']}/approve", headers={**copper["gm"], "If-Match": "99"})
        assert r.status_code == 412
    review = await action(client, copper, "price_review")
    if review["status"] == "proposed":
        r = await client.post(f"/api/v1/actions/{review['id']}/approve", headers=copper["gm"])
        assert r.status_code == 403  # price reviews belong to the Owner
        r = await client.post(f"/api/v1/actions/{review['id']}/adjust", headers={**copper["owner"], "If-Match": str(
            review["version"])}, json={"parameters": {"suggested_gross_minor": 1050}, "note": "Round to 10.50"})
        assert r.status_code == 200, r.text
        adjusted = r.json()
        assert adjusted["version"] == review["version"] + 1 and adjusted["parameters"]["suggested_gross_minor"] == 1050
        assert adjusted["expected_impact_minor"] > review["expected_impact_minor"]
        r = await client.post(f"/api/v1/actions/{review['id']}/adjust", headers=copper["owner"],
                              json={"parameters": {"menu_item_id": str(uuid.uuid4())}})
        assert r.status_code == 409 and r.json()["code"] == "not_adjustable"
        r = await client.post(f"/api/v1/actions/{review['id']}/reject", headers=copper["owner"],
                              json={"reason": "Keep 9.50 until the menu reprint"})
        assert r.status_code == 200 and r.json()["status"] == "rejected"
    r = await client.post(f"/api/v1/actions/{review['id']}/approve", headers=copper["owner"])
    assert r.status_code == 409 and r.json()["code"] == "illegal_transition"


async def test_supplier_switch_commits_and_emails_po(client, copper):
    """Exit: GM approval -> executor (worker) -> draft PO to Bramley committed within the GM's PO limit ->
    supplier emailed through the MailPort with a recorded delivery; replay is a no-op."""
    case = await demo_friday(client, copper)
    switch = await approve(client, copper, "supplier_switch")
    assert switch["status"] == "follow_up", switch
    assert switch["execution"]["success"] and switch["execution"]["key"] == f"{switch['id']}:{switch['version']}"
    result = switch["execution"]["result"]
    assert result["po_status"] == "committed" and result["emailed_to"] == "sales@bramleypoultry.example"

    cat = Catalogue(COPPER_POT)
    site = uuid.UUID(copper["site"])
    async with tenant_unit_of_work(cat.org_id, site) as s:
        po = (await s.execute(select(PurchaseOrder).where(
            PurchaseOrder.recommendation_id == uuid.UUID(switch["id"])))).scalar_one()
        mail = (await s.execute(select(EmailDelivery).where(EmailDelivery.related_id == po.id))).scalar_one()
    assert po.supplier_id == cat.supplier_ids["BRM"] and po.status == "committed" and po.approved_by
    assert mail.status in ("logged", "sent", "accepted") and mail.attempts == 1 and "Bramley" in mail.text

    po_detail = (await client.get(f"/api/v1/purchase-orders/{po.id}", headers=copper["chef"])).json()
    assert po_detail["lines"][0]["unit_price_minor"] == 719 and "supplier_switch" in po_detail["lines"][0]["reason_codes"]
    assert po_detail["emails"][0]["status"] == mail.status

    # Replay of the execution job: no second PO, no second email.
    async with tenant_unit_of_work(cat.org_id, site) as s:
        ctx = await build_site_context(s, cat.org_id, site, actor="test")
        rec = await run_execution(ctx, uuid.UUID(switch["id"]), switch["version"], "general_manager")
        assert rec.status == "follow_up"
    async with tenant_unit_of_work(cat.org_id, site) as s:
        pos = (await s.execute(select(func.count()).select_from(PurchaseOrder).where(
            PurchaseOrder.recommendation_id == uuid.UUID(switch["id"])))).scalar()
        execs = (await s.execute(select(func.count()).select_from(RecommendationExecution).where(
            RecommendationExecution.recommendation_id == uuid.UUID(switch["id"])))).scalar()
        default = (await s.execute(select(Recommendation.status).where(
            Recommendation.id == uuid.UUID(switch["id"])))).scalar_one()
    assert pos == 1 and execs == 1 and default == "follow_up"

    timeline = (await client.get(f"/api/v1/cases/{case['case_id']}/timeline", headers=copper["gm"])).json()
    kinds = [e["kind"] for e in timeline]
    for step in ("detected", "investigated", "proposed", "approved", "executing", "executed", "follow_up_scheduled"):
        assert step in kinds, kinds
    assert kinds.index("detected") < kinds.index("investigated") < kinds.index("approved") < kinds.index("executed")


async def test_po_commit_respects_limits(client, copper):
    """FR-PRC-08: a draft PO is committed only by a role within its limit."""
    await demo_friday(client, copper)
    par = await action(client, copper, "par_level_change")
    if par["status"] == "proposed":
        par = await approve(client, copper, "par_level_change")
    assert par["status"] == "follow_up" and par["execution"]["result"]["par_level_base_to"] > 18000
    pos = (await client.get("/api/v1/purchase-orders", headers=copper["chef"], params={"status": "draft"})).json()
    if pos:
        r = await client.post(f"/api/v1/purchase-orders/{pos[0]['id']}/approve", headers=copper["shift"])
        assert r.status_code == 403


async def test_cases_are_tenant_scoped(client, copper, seeded):
    """Northside users get 404 on Copper Pot cases and actions."""
    case = await demo_friday(client, copper)
    lds = site_id(NORTHSIDE, "NK-LDS")
    nk = auth(await demo_token(client, NORTHSIDE, "gm.leeds@northside.example"), lds)
    assert (await client.get(f"/api/v1/cases/{case['case_id']}", headers=nk)).status_code == 404
    rec_id = next(iter(case["recs"].values()))
    assert (await client.get(f"/api/v1/actions/{rec_id}", headers=nk)).status_code == 404
    assert (await client.post(f"/api/v1/actions/{rec_id}/approve", headers=nk)).status_code == 404
