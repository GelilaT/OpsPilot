"""Flow 2 (FR-MNU-02/03/05/06, FR-PRC-02/03/04, FR-ANO-01..05, FR-RCA-01..07): the S1/S2 Friday.

Exit criterion (plan Step 4): the Friday drop yields cause supplier_short_delivery ~0.86 and Chicken Wrap
GP 68.1% -> 64.3% (SRS Appendix B).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.tenancy.scoping import tenant_unit_of_work
from app.domain.actions.models import OperationsCase
from app.domain.intelligence.models import Anomaly, Investigation
from app.domain.investigation.number_guard import check_narrative
from app.domain.purchasing.models import GoodsReceipt, GoodsReceiptLine, PurchaseOrder
from app.simulation.catalogue import Catalogue, sid
from app.simulation.profiles import COPPER_POT
from tests.conftest import make_token
from tests.integration.scenario import FRIDAY, demo_friday
from tests.integration.test_step3_invoices import CRON

pytestmark = pytest.mark.integration


async def demo_token(client, profile, email: str) -> str:
    user_id = sid(profile.slug, "user", email).hex
    claims = (await client.get(f"/internal/auth/claims/{user_id}", headers=CRON)).json()
    return make_token(user_id, email=email, organisation_id=claims["organisation_id"], org_role=claims["org_role"],
                      sites=claims["sites"])


def site_id(profile, code: str) -> str:
    return str(Catalogue(profile).site_id(next(s for s in profile.sites if s.code == code)))


async def run_nightly(org_id: uuid.UUID, site: str, *days: str) -> list[dict]:
    from app.workers.nightly_tasks import execute_nightly_pipeline

    return [await execute_nightly_pipeline(organisation_id=str(org_id), site_id=site, business_date=d) for d in days]


def node(graph: dict, node_id: str) -> dict:
    return next(n for n in graph["nodes"] if n["id"] == node_id)


async def test_chicken_wrap_margin_s1(client, copper):
    """FR-MNU-02/03: WAC-based item cost; GP 68.1% (start of the 28-day window) -> 64.3% after INV-4471."""
    await demo_friday(client, copper)
    h = copper["gm"]
    items = (await client.get("/api/v1/menu/items", headers=h)).json()
    wrap = next(i for i in items if i["code"] == "chicken_wrap")
    timeline = (await client.get(f"/api/v1/menu/items/{wrap['id']}/cost-timeline", headers=h,
                                 params={"from": "2026-09-04", "to": "2026-10-02"})).json()
    by_day = {row["business_date"]: row for row in timeline}
    assert Decimal(str(by_day["2026-09-04"]["gp_pct"])) == Decimal("68.1")
    assert by_day["2026-09-04"]["cost_minor"] == 253
    assert Decimal(str(by_day["2026-10-01"]["gp_pct"])) == Decimal("67.3")  # tortilla wraps 0.28 -> 0.34 on 15 Sep
    assert Decimal(str(by_day["2026-10-02"]["gp_pct"])) == Decimal("64.3")
    assert by_day["2026-10-02"]["cost_minor"] == 283

    attr = (await client.get(f"/api/v1/menu/items/{wrap['id']}/attribution", headers=h,
                             params={"from": "2026-09-04", "to": "2026-10-02"})).json()
    top = attr["drivers"][0]
    assert top["ingredient_name"].startswith("Chicken thigh") and Decimal(str(top["pct_of_change"])) == Decimal("80.0")
    assert top["supplier_name"] == "Ashworth Meats Ltd"

    # FR-MNU-06: the price restoring the 65% target, rounded to the site's endings (Appendix B: 9.50 -> 9.95).
    what_if = (await client.post(f"/api/v1/menu/items/{wrap['id']}/what-if", headers=h)).json()
    assert what_if["current_gross_minor"] == 950 and what_if["suggested_gross_minor"] == 995
    assert Decimal(str(what_if["suggested_gp_pct"])) == Decimal("65.9")
    assert what_if["weekly_gp_impact_minor"] > what_if["weekly_gp_impact_lower_volume_minor"] > 0


async def test_friday_investigation_s2(client, copper):
    """Exit: the Friday drop is explained as supplier short delivery -> stock-out with confidence ~0.86."""
    case = await demo_friday(client, copper)
    h = copper["gm"]
    inv = (await client.get(f"/api/v1/investigations/{case['investigation_id']}", headers=h)).json()
    causes = inv["narrative"]["causes"]
    top = causes[0]
    assert top["cause_code"] == "supplier_short_delivery" and top["chain"] == ["supplier_short_delivery", "stock_out"]
    assert 0.84 <= top["confidence"] <= 0.88, causes
    assert all(c["confidence"] >= 0.3 for c in causes)  # hidden below the threshold

    g = inv["graph"]
    a = node(g, "anomaly")["facts"]
    assert a["severity"] == "critical" and a["deviation_pct"] < -15 and a["weekday"] == "Friday"
    d = node(g, "decomposition")["facts"]
    assert abs(d["orders_effect"] + d["spend_effect"] - d["total_change"]) < 0.02  # LMDI parts add up
    assert d["spend_pct"] < d["orders_pct"] < 0  # the spend fell more than the orders
    items = node(g, "items")["facts"]
    assert items["ingredient"].startswith("Chicken thigh") and items["dishes"] == 4 and items["units_pct"] < -30
    conc = node(g, "concentration")["facts"]
    assert conc["segment"] == "Friday dinner" and conc["concentrated"] and conc["share_pct"] >= 60
    stock = node(g, "stock")["facts"]
    assert stock["out_at"] == conc["last_focus_sale"] and stock["need_after"] > 0
    buy = node(g, "purchasing")["facts"]
    assert buy["invoice_number"] == "INV-4471" and buy["ordered"] == 20 and buy["invoiced"] == 12
    assert buy["short_pct"] == 40 and buy["price"] == 7.9 and buy["median_price_90d"] == 6.7
    margin = node(g, "margin")["facts"]
    assert (margin["item"], margin["cost_from"], margin["cost_to"], margin["gp_from"], margin["gp_to"]) == (
        "Chicken Wrap", 2.53, 2.83, 68.1, 64.3)
    assert margin["top_driver"].startswith("Chicken thigh") and margin["top_driver_pct"] == 80
    ruled = node(g, "ruled_out")["facts"]
    assert "weather_effect" in ruled and "discount_or_void_spike" in ruled
    assert {"supplier:" + str(Catalogue(COPPER_POT).supplier_ids["ASH"]),
            "ingredient:" + str(Catalogue(COPPER_POT).ingredient_ids["chicken_thigh"])} <= set(g["causal_entities"])

    # The van still arrived after the invoice was posted: the goods receipt (12 kg) links to INV-4471 and the
    # PO is part-received, so the three-way facts agree.
    cat = Catalogue(COPPER_POT)
    async with tenant_unit_of_work(cat.org_id, uuid.UUID(copper["site"])) as s:
        grn = (await s.execute(select(GoodsReceipt).where(
            GoodsReceipt.id == sid(COPPER_POT.slug, "goods_receipt", "CP1", "ASH", FRIDAY)))).scalar_one()
        chicken = (await s.execute(select(GoodsReceiptLine.qty_base).where(
            GoodsReceiptLine.goods_receipt_id == grn.id,
            GoodsReceiptLine.ingredient_id == cat.ingredient_ids["chicken_thigh"]))).scalar_one()
        po = (await s.execute(select(PurchaseOrder).where(PurchaseOrder.number == "PO-CP1-261002-ASH"))).scalar_one()
    assert grn.invoice_number == "INV-4471" and grn.invoice_id is not None and chicken == Decimal(12000)
    assert po.status == "part_received" and buy["received"] == 12

    # FR-RCA-07: the narrative cites existing nodes and every number passes the Number Guard.
    assert inv["narrative"]["guard_violations"] == [] and check_narrative(inv["narrative"]["text"], g["nodes"]) == []
    assert inv["finding"].startswith("Friday dinner") and "0.86" in inv["finding"]
    # FR-RCA-06: recommendation drafts for the Action Centre.
    assert {"supplier_switch", "par_level_change", "price_review"} <= {d["type"] for d in inv["draft_recommendations"]}


async def test_one_incident_one_case_and_idempotent_rerun(client, copper):
    """FR-ANO-03/05 + FR-ACT-11: related same-day anomalies fold into the Friday case; re-running the night
    neither duplicates anomalies nor reopens investigations."""
    case = await demo_friday(client, copper)
    cat = Catalogue(COPPER_POT)
    site = uuid.UUID(copper["site"])
    async with tenant_unit_of_work(cat.org_id, site) as s:
        before = (await s.execute(select(func.count()).select_from(Anomaly).where(Anomaly.site_id == site))).scalar()
        folded = (await s.execute(select(Anomaly.detector, Anomaly.subject).where(
            Anomaly.parent_id == uuid.UUID(case["anomaly_id"])))).all()
        invs = (await s.execute(select(func.count()).select_from(Investigation).where(
            Investigation.anomaly_id == uuid.UUID(case["anomaly_id"])))).scalar()
    detectors = {d for d, _ in folded}
    assert {"stock_out", "price_increase", "margin_decline"} <= detectors
    assert any(subj.get("code") == "chicken_thigh" for d, subj in folded if d == "price_increase")

    result = (await run_nightly(cat.org_id, copper["site"], FRIDAY.isoformat()))[0]
    assert result["new_anomalies"] == 0 and result["investigations"] == 0
    async with tenant_unit_of_work(cat.org_id, site) as s:
        after = (await s.execute(select(func.count()).select_from(Anomaly).where(Anomaly.site_id == site))).scalar()
        invs_after = (await s.execute(select(func.count()).select_from(Investigation).where(
            Investigation.anomaly_id == uuid.UUID(case["anomaly_id"])))).scalar()
        cases = (await s.execute(select(func.count()).select_from(OperationsCase).where(
            OperationsCase.anomaly_id == uuid.UUID(case["anomaly_id"])))).scalar()
    assert after == before and invs_after == invs and cases == 1


async def test_supplier_comparison_and_attribution(client, copper):
    """FR-PRC-03/04/10: Bramley 7.19/kg at 97% fill rate is the switch candidate; chicken leads attribution."""
    await demo_friday(client, copper)
    cat = Catalogue(COPPER_POT)
    h = copper["gm"]
    cmp = (await client.get("/api/v1/procurement/comparison", headers=h,
                            params={"ingredient_id": str(cat.ingredient_ids["chicken_thigh"])})).json()
    by_name = {o["supplier_name"]: o for o in cmp["offers"]}
    bramley, ashworth = by_name["Bramley Poultry & Fish Ltd"], by_name["Ashworth Meats Ltd"]
    assert bramley["rank"] == 1 and Decimal(bramley["price_per_base_minor"]) == Decimal("0.719")
    assert Decimal(bramley["fill_rate"]) >= Decimal("0.95") and ashworth["is_default"]
    assert cmp["switch_to"] == bramley["supplier_id"] and Decimal(cmp["switch_saving_pct"]) > Decimal("0.05")

    attr = (await client.get("/api/v1/procurement/cost-attribution", headers=h,
                             params={"from": "2026-09-19", "to": "2026-10-02"})).json()
    assert attr["total_delta_minor"] > 0 and attr["suppliers"]
    assert sum(r["delta_cost_minor"] for r in attr["ingredients"]) == attr["total_delta_minor"]


async def test_dismissed_fingerprint_is_suppressed(client, copper):
    """FR-ANO-06: an anomaly dismissed as expected does not come back for 7 days."""
    await demo_friday(client, copper)
    h = copper["gm"]
    info = (await client.get("/api/v1/anomalies", headers=h, params={"severity": "info", "limit": 200})).json()
    target = next(a for a in info if a["detector"] == "price_increase" and a["parent_id"] is None)
    r = await client.post(f"/api/v1/anomalies/{target['id']}/dismiss", headers=h, json={"reason": "Expected rise"})
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    cat = Catalogue(COPPER_POT)
    await run_nightly(cat.org_id, copper["site"], FRIDAY.isoformat())
    again = (await client.get("/api/v1/anomalies", headers=h, params={"detector": "price_increase", "limit": 200})).json()
    same = [a for a in again if a["subject"]["id"] == target["subject"]["id"] and a["period_end"] == target["period_end"]]
    assert len(same) == 1 and same[0]["status"] == "dismissed"
    assert date.fromisoformat(same[0]["dismissed_until"]) > FRIDAY
