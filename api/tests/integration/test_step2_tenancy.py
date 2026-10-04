"""Phase 2a exit criterion: both organisations seed from the same code; cross-tenant access returns 404.

Also covers configuration resolution, integration connections, row-level security, the seeded ledger
and "simulate next day" through the PosPort.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select, text

from app.core.tenancy.scoping import system_unit_of_work, tenant_unit_of_work
from app.domain.inventory.models import Ingredient, StockMovement
from app.domain.inventory.services import theoretical_usage
from app.domain.menu.models import MenuItem
from app.domain.purchasing.models import GoodsReceiptLine, Supplier
from app.domain.sales.models import SalesOrder
from app.simulation.catalogue import Catalogue, sid
from app.simulation.profiles import COPPER_POT, NORTHSIDE
from app.simulation.scenarios import SEED_END
from tests.conftest import auth, make_token

pytestmark = pytest.mark.integration
CRON = {"X-Cron-Secret": "test-cron-secret"}
DAYS = 21


async def demo_token(client, profile, email: str) -> str:
    user_id = sid(profile.slug, "user", email).hex
    claims = (await client.get(f"/internal/auth/claims/{user_id}", headers=CRON)).json()
    return make_token(user_id, email=email, organisation_id=claims["organisation_id"], org_role=claims["org_role"],
                      sites=claims["sites"])


def site_id(profile, code: str) -> str:
    return str(Catalogue(profile).site_id(next(s for s in profile.sites if s.code == code)))


async def test_both_organisations_seeded_from_the_same_code(seeded, client):
    assert seeded[COPPER_POT.slug]["sales_order"] > 1000 and seeded[NORTHSIDE.slug]["sales_order"] > 1000
    for profile, n_sites in ((COPPER_POT, 1), (NORTHSIDE, 2)):
        org = Catalogue(profile).org_id
        async with tenant_unit_of_work(org) as s:
            assert (await s.execute(select(func.count()).select_from(MenuItem))).scalar() == 42
            assert (await s.execute(select(func.count()).select_from(Ingredient))).scalar() == 65
            assert (await s.execute(select(func.count()).select_from(Supplier))).scalar() == 6
        owner = await demo_token(client, profile, profile.users[0].email)
        sites = (await client.get("/api/v1/sites", headers=auth(owner))).json()
        assert len(sites) == n_sites


async def test_demo_users_have_site_scoped_roles(seeded, client):
    leeds_gm = await demo_token(client, NORTHSIDE, "gm.leeds@northside.example")
    me = (await client.get("/api/v1/me", headers=auth(leeds_gm))).json()
    assert [s["name"] for s in me["sites"]] == ["Northside Kitchens - Leeds"]
    assert me["display_name"] == "Ravi D." and me["org_role"] is None


async def test_cross_tenant_access_returns_404(seeded, client):
    cp_owner = await demo_token(client, COPPER_POT, "owner@copperpot.example")
    nk_owner = await demo_token(client, NORTHSIDE, "owner@northside.example")
    leeds_gm = await demo_token(client, NORTHSIDE, "gm.leeds@northside.example")
    leeds, york, cp1 = site_id(NORTHSIDE, "NK-LDS"), site_id(NORTHSIDE, "NK-YRK"), site_id(COPPER_POT, "CP1")

    assert (await client.get("/api/v1/simulator/state", headers=auth(cp_owner, leeds))).status_code == 404
    assert (await client.get("/api/v1/simulator/state", headers=auth(nk_owner, cp1))).status_code == 404
    # Same organisation, but not a member of that site:
    assert (await client.get("/api/v1/simulator/state", headers=auth(leeds_gm, york))).status_code == 404
    assert (await client.get("/api/v1/simulator/state", headers=auth(leeds_gm, leeds))).status_code == 200
    # Organisation-level listings never leak the other tenant.
    cp_integrations = (await client.get("/api/v1/integrations", headers=auth(cp_owner))).json()
    assert {c["site_id"] for c in cp_integrations["connections"]} == {cp1}
    r = await client.get("/api/v1/config", headers=auth(cp_owner), params={"scope": "site", "site_id": leeds})
    assert r.status_code == 404


async def test_row_level_security_blocks_other_tenants_in_sql(seeded):
    cp, nk = Catalogue(COPPER_POT).org_id, Catalogue(NORTHSIDE).org_id
    async with tenant_unit_of_work(cp) as s:
        total = (await s.execute(text("SELECT count(*) FROM sales_order"))).scalar()
        leaked = (await s.execute(text("SELECT count(*) FROM sales_order WHERE organisation_id = :o"), {"o": nk})).scalar()
        orm = (await s.execute(select(func.count()).select_from(SalesOrder))).scalar()
    async with system_unit_of_work() as s:
        cp_only = (await s.execute(text("SELECT count(*) FROM sales_order WHERE organisation_id = :o"), {"o": cp})).scalar()
    assert leaked == 0 and total == cp_only == orm
    # Writes into another tenant are rejected by the policy's WITH CHECK.
    with pytest.raises(Exception, match="row-level security"):
        async with tenant_unit_of_work(cp) as s:
            await s.execute(text("UPDATE supplier SET email = 'x@example.com' WHERE true"))
            await s.execute(text("INSERT INTO supplier (id, organisation_id, name, normalised_name, lead_time_days, "
                                 "delivery_weekdays, currency, active) VALUES (gen_random_uuid(), :o, 'X', 'x', 1, "
                                 "'[]', 'GBP', true)"), {"o": nk})


async def test_configuration_resolves_site_then_organisation_then_system(seeded, client):
    nk_owner = await demo_token(client, NORTHSIDE, "owner@northside.example")
    cp_owner = await demo_token(client, COPPER_POT, "owner@copperpot.example")
    leeds, york = site_id(NORTHSIDE, "NK-LDS"), site_id(NORTHSIDE, "NK-YRK")

    def value(entries, key):
        return next((e["value"], e["source"]) for e in entries if e["key"] == key)

    cp = (await client.get("/api/v1/config", headers=auth(cp_owner))).json()
    nk = (await client.get("/api/v1/config", headers=auth(nk_owner))).json()
    assert value(cp, "invoice.price_increase_pct") == (0.05, "system")
    assert value(nk, "invoice.price_increase_pct") == (0.07, "organisation")

    r = await client.put("/api/v1/config", headers=auth(nk_owner), params={"scope": "site", "site_id": york},
                         json={"values": {"invoice.price_increase_pct": 0.08}})
    assert r.status_code == 200 and r.json()[0]["source"] == "site" and r.json()[0]["version"] == 1
    york_cfg = (await client.get("/api/v1/config", headers=auth(nk_owner), params={"scope": "site", "site_id": york})).json()
    leeds_cfg = (await client.get("/api/v1/config", headers=auth(nk_owner), params={"scope": "site", "site_id": leeds})).json()
    assert value(york_cfg, "invoice.price_increase_pct") == (0.08, "site")
    assert value(leeds_cfg, "invoice.price_increase_pct") == (0.07, "organisation")

    bad = await client.put("/api/v1/config", headers=auth(nk_owner), json={"values": {"invoice.price_increase_pct": "x"}})
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_config_value"
    unknown = await client.put("/api/v1/config", headers=auth(nk_owner), json={"values": {"made.up": 1}})
    assert unknown.status_code == 422
    gm = await demo_token(client, NORTHSIDE, "gm.leeds@northside.example")
    assert (await client.get("/api/v1/config", headers=auth(gm))).status_code == 403

    cleared = await client.put("/api/v1/config", headers=auth(nk_owner), params={"scope": "site", "site_id": york},
                               json={"values": {"invoice.price_increase_pct": None}})
    assert cleared.json()[0]["source"] == "organisation"
    audit = (await client.get("/api/v1/audit", headers=auth(nk_owner), params={"entity_type": "config_value"})).json()
    assert {i["action"] for i in audit["items"]} >= {"set", "clear"}


async def test_integration_connections_select_adapters_by_configuration(seeded, client):
    owner = await demo_token(client, COPPER_POT, "owner@copperpot.example")
    view = (await client.get("/api/v1/integrations", headers=auth(owner))).json()
    effective = {(e["kind"], e["site_id"]): (e["provider"], e["source"]) for e in view["effective"]}
    cp1 = site_id(COPPER_POT, "CP1")
    assert effective[("pos", cp1)] == ("simulator", "site")
    assert effective[("ai", None)][1] == "system"
    assert "sendgrid" in view["available"]["mail"] and "gcs" in view["available"]["storage"]

    # Switch storage to the in-memory adapter for the organisation and test it.
    r = await client.post("/api/v1/integrations", headers=auth(owner), json={"kind": "storage", "provider": "memory"})
    assert r.status_code == 201
    test = (await client.post(f"/api/v1/integrations/{r.json()['id']}/test", headers=auth(owner))).json()
    assert test == {"ok": True, "provider": "memory", "detail": "write and read succeeded"}

    # SendGrid with a missing secret fails the test with a typed credentials error, not a crash.
    r = await client.post("/api/v1/integrations", headers=auth(owner),
                          json={"kind": "mail", "provider": "sendgrid", "secret_ref": "env:OPSPILOT_MISSING_KEY"})
    test = (await client.post(f"/api/v1/integrations/{r.json()['id']}/test", headers=auth(owner))).json()
    assert test["ok"] is False and "InvalidCredentialsError" in test["detail"]

    # POS simulator test and an unknown provider.
    pos_id = next(c["id"] for c in view["connections"] if c["kind"] == "pos")
    assert (await client.post(f"/api/v1/integrations/{pos_id}/test", headers=auth(owner))).json()["ok"] is True
    r = await client.post("/api/v1/integrations", headers=auth(owner), json={"kind": "pos", "provider": "toast"})
    assert r.status_code == 422 and r.json()["code"] == "unknown_provider"
    # Restore defaults for the other tests.
    for kind in ("storage", "mail"):
        await client.post("/api/v1/integrations", headers=auth(owner),
                          json={"kind": kind, "provider": "local" if kind == "storage" else "console"})


async def test_seeded_ledger_matches_recipes_times_sales(seeded):
    """Seed consumption movements equal the theoretical-usage SQL used nightly (FR-STK-03)."""
    cat = Catalogue(COPPER_POT)
    site = cat.site_id(COPPER_POT.sites[0])
    day = SEED_END - timedelta(days=3)
    async with tenant_unit_of_work(cat.org_id, site) as s:
        expected = await theoretical_usage(s, site, day)
        rows = (await s.execute(select(StockMovement.ingredient_id, StockMovement.qty_base).where(
            StockMovement.business_date == day, StockMovement.type == "theoretical_consumption"))).all()
    assert len(rows) == len(expected) > 20
    for ingredient_id, qty in rows:
        assert abs(-qty - expected[ingredient_id]) < Decimal("0.01")


async def run_worker() -> None:
    from app.workers.app import app as proc_app

    async with proc_app.open_async():
        await proc_app.run_worker_async(wait=False, install_signal_handlers=False, listen_notify=False)


async def test_simulate_next_day_through_the_pos_port(seeded, client):
    """FR-ING-02/04: one simulated day through the PosPort (Northside Leeds; the Copper Pot Friday is the
    Flow 1-4 demo and is exercised in test_step4..6)."""
    owner = await demo_token(client, NORTHSIDE, "owner@northside.example")
    lds = site_id(NORTHSIDE, "NK-LDS")
    h = auth(owner, lds)
    state = (await client.get("/api/v1/simulator/state", headers=h)).json()
    assert state["enabled"] and state["business_date"] == SEED_END.isoformat()

    bad = await client.post("/api/v1/simulator/next-day", headers=h, json={"scenario": "S2"})
    assert bad.status_code == 422 and "not planted" in bad.json()["detail"]
    chef = await demo_token(client, NORTHSIDE, "chef.leeds@northside.example")
    assert (await client.post("/api/v1/simulator/next-day", headers=auth(chef, lds), json={})).status_code == 403

    r = await client.post("/api/v1/simulator/next-day", headers=h, json={})
    assert r.status_code == 202
    again = await client.post("/api/v1/simulator/next-day", headers=h, json={})
    assert again.status_code == 409  # the same day cannot be queued twice
    await run_worker()
    run = (await client.get(f"/api/v1/jobs/runs/{r.json()['id']}", headers=h)).json()
    assert run["status"] == "succeeded", run["error"]
    result = run["result"]
    assert result["business_date"] == "2026-10-02" and result["scenarios"] == []
    assert len(result["awaiting_invoice_upload"]) == 1  # the KMP delivery is booked when its invoice is posted
    assert result["orders"] > 100

    cat = Catalogue(NORTHSIDE)
    async with tenant_unit_of_work(cat.org_id, uuid.UUID(lds)) as s:
        day = date(2026, 10, 2)
        orders = (await s.execute(select(func.count()).select_from(SalesOrder).where(
            SalesOrder.site_id == uuid.UUID(lds), SalesOrder.business_date == day))).scalar()
        consumption = (await s.execute(select(func.count()).select_from(StockMovement).where(
            StockMovement.site_id == uuid.UUID(lds), StockMovement.business_date == day,
            StockMovement.type == "theoretical_consumption"))).scalar()
        grn = (await s.execute(select(func.count()).select_from(GoodsReceiptLine).where(
            GoodsReceiptLine.goods_receipt_id == sid(NORTHSIDE.slug, "goods_receipt", "NK-LDS", "KMP", day)))).scalar()
    assert orders == result["orders"] and consumption > 20 and grn > 0
    state = (await client.get("/api/v1/simulator/state", headers=h)).json()
    assert state["business_date"] == "2026-10-02"

    # Re-ingesting the same POS day is idempotent on (site, external_order_id).
    from app.core.tenancy.context import build_site_context
    from app.domain.sales.services import ingest_day

    async with tenant_unit_of_work(cat.org_id, uuid.UUID(lds)) as s:
        ctx = await build_site_context(s, cat.org_id, uuid.UUID(lds), actor="test")
        again_result = await ingest_day(ctx, day)
    assert again_result.orders == orders and again_result.new_orders == 0


async def test_signed_file_urls(seeded, client):
    from app.core.integrations import registry
    from app.ports import IntegrationKind

    cat = Catalogue(NORTHSIDE)
    storage = registry.build(IntegrationKind.storage, "local", organisation_id=cat.org_id, site_id=None, settings={},
                             secret_ref=None)
    key = f"tests/{uuid.uuid4().hex}.pdf"
    await storage.put(b"%PDF-1.7 test", key=key, content_type="application/pdf")
    url = httpx.URL(await storage.signed_url(key, ttl_seconds=60, content_type="application/pdf"))
    r = await client.get(url.raw_path.decode())
    assert r.status_code == 200 and r.content == b"%PDF-1.7 test"
    assert r.headers["x-content-type-options"] == "nosniff" and "sandbox" in r.headers["content-security-policy"]
    tampered = url.copy_set_param("sig", "AAAA")
    assert (await client.get(tampered.raw_path.decode())).status_code == 404
