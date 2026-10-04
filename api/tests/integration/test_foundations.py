"""Phase 1 exit criterion: authenticated CRUD with audit, and a job round-trip (SRS Appendix D)."""

import uuid

import pytest
from sqlalchemy import select, text

from app.core.audit import AuditEvent
from app.core.db import get_sessionmaker
from app.core.tenancy.scoping import tenant_unit_of_work
from tests.conftest import auth, make_token

pytestmark = pytest.mark.integration

CRON = {"X-Cron-Secret": "test-cron-secret"}


async def onboard(client, name: str = "The Copper Pot", sites: int = 1) -> dict:
    """Sign up a new owner, create an organisation (+ sites) and return a token with fresh claims."""
    user_id = f"user_{uuid.uuid4().hex[:10]}"
    email = f"{user_id}@example.test"
    token = make_token(user_id, email=email, name="Gelila Tefera")
    r = await client.post("/api/v1/organisations", headers=auth(token), json={
        "name": name,
        "first_site": {"name": f"{name} - Central", "timezone": "Europe/London", "currency": "GBP",
                       "latitude": "53.4808", "longitude": "-2.2426"},
    })
    assert r.status_code == 201, r.text
    org = r.json()["organisation"]
    claims = (await client.get(f"/internal/auth/claims/{user_id}", headers=CRON)).json()
    token = make_token(user_id, email=email, organisation_id=claims["organisation_id"],
                       org_role=claims["org_role"], sites=claims["sites"])
    site_ids = list(claims["sites"])
    for i in range(1, sites):
        r = await client.post("/api/v1/sites", headers=auth(token),
                              json={"name": f"{name} - Site {i + 1}", "timezone": "Europe/London"})
        assert r.status_code == 201, r.text
        site_ids.append(r.json()["id"])
    if sites > 1:
        claims = (await client.get(f"/internal/auth/claims/{user_id}", headers=CRON)).json()
        token = make_token(user_id, email=email, organisation_id=claims["organisation_id"],
                           org_role=claims["org_role"], sites=claims["sites"])
    return {"user_id": user_id, "org_id": org["id"], "site_ids": site_ids, "token": token, "email": email}


async def test_health(client):
    assert (await client.get("/health/ready")).json() == {"status": "ok", "database": "ok"}


async def test_unauthenticated_is_problem_json(client):
    r = await client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "unauthorized" and body["request_id"] == r.headers["x-request-id"]


async def test_expired_and_wrong_audience_tokens_rejected(client):
    r = await client.get("/api/v1/me", headers=auth(make_token(ttl=-60)))
    assert r.status_code == 401 and r.json()["code"] == "token_expired"
    r = await client.get("/api/v1/me", headers=auth(make_token(aud="http://evil")))
    assert r.status_code == 401


async def test_validation_errors_have_field_details(client):
    r = await client.post("/api/v1/organisations", headers=auth(make_token()), json={"name": ""})
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "name"


async def test_onboarding_writes_audit_in_same_transaction(client):
    o = await onboard(client)
    me = (await client.get("/api/v1/me", headers=auth(o["token"]))).json()
    assert me["organisation"]["id"] == o["org_id"]
    assert me["org_role"] == "owner" and len(me["sites"]) == 1
    assert me["display_name"] == "Gelila T."  # first name + last initial only

    async with tenant_unit_of_work(uuid.UUID(o["org_id"])) as s:
        events = (await s.execute(select(AuditEvent.entity_type, AuditEvent.action).where(
            AuditEvent.organisation_id == uuid.UUID(o["org_id"])))).all()
    assert {("organisation", "create"), ("membership", "create"), ("site", "create")} <= set(events)

    page = (await client.get("/api/v1/audit", headers=auth(o["token"]), params={"limit": 2})).json()
    assert len(page["items"]) == 2 and page["next_cursor"]


async def test_cannot_create_second_organisation(client):
    o = await onboard(client)
    r = await client.post("/api/v1/organisations", headers=auth(o["token"]), json={"name": "Another"})
    assert r.status_code == 409 and r.json()["code"] == "already_member"


async def test_cross_tenant_access_returns_404(client):
    a = await onboard(client, "Org A")
    b = await onboard(client, "Org B")
    run = await client.post("/api/v1/jobs/runs", headers=auth(a["token"], a["site_ids"][0]),
                            json={"task": "system.echo", "payload": {"n": 1}})
    assert run.status_code == 202
    run_id = run.json()["id"]
    # B cannot use A's site at all ...
    r = await client.get(f"/api/v1/jobs/runs/{run_id}", headers=auth(b["token"], a["site_ids"][0]))
    assert r.status_code == 404
    # ... nor reach A's resource through its own site.
    r = await client.get(f"/api/v1/jobs/runs/{run_id}", headers=auth(b["token"], b["site_ids"][0]))
    assert r.status_code == 404
    # B's audit log contains nothing of A.
    items = (await client.get("/api/v1/audit", headers=auth(b["token"]), params={"limit": 200})).json()["items"]
    assert all(i["entity_id"] != run_id for i in items)


async def test_role_enforced_per_site(client):
    o = await onboard(client)
    chef = make_token(organisation_id=o["org_id"], sites={o["site_ids"][0]: "head_chef"})
    r = await client.post("/api/v1/jobs/runs", headers=auth(chef, o["site_ids"][0]),
                          json={"task": "system.echo"})
    assert r.status_code == 403
    r = await client.get("/api/v1/audit", headers=auth(chef))
    assert r.status_code == 403


async def test_idempotency_key_replays_and_conflicts(client):
    token = make_token()
    h = auth(token, **{"Idempotency-Key": "org-create-1"})
    first = await client.post("/api/v1/organisations", headers=h, json={"name": "Idem Bistro"})
    again = await client.post("/api/v1/organisations", headers=h, json={"name": "Idem Bistro"})
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json() and again.headers.get("idempotent-replayed") == "true"
    other = await client.post("/api/v1/organisations", headers=h, json={"name": "Different"})
    assert other.status_code == 409 and other.json()["code"] == "idempotency_key_reused"


async def test_internal_requires_service_auth(client):
    assert (await client.get("/internal/auth/claims/x")).status_code == 404
    assert (await client.get("/internal/auth/claims/x", headers={"X-Cron-Secret": "wrong"})).status_code == 404


async def test_audit_log_is_append_only(migrated_db):
    async with get_sessionmaker()() as s:
        with pytest.raises(Exception, match=r"append-only|permission denied"):
            async with s.begin():
                await s.execute(text("UPDATE audit_event SET action = 'tampered'"))


async def run_worker_until_idle() -> None:
    from app.workers.app import app as proc_app

    async with proc_app.open_async():
        await proc_app.run_worker_async(wait=False, install_signal_handlers=False, listen_notify=False)


async def test_job_round_trip(client):
    o = await onboard(client)
    h = auth(o["token"], o["site_ids"][0])
    r = await client.post("/api/v1/jobs/runs", headers=h, json={"task": "system.echo", "payload": {"hello": "ops"}})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    run_id = r.json()["id"]

    await run_worker_until_idle()

    run = (await client.get(f"/api/v1/jobs/runs/{run_id}", headers=h)).json()
    assert run["status"] == "succeeded" and run["result"] == {"echo": {"hello": "ops"}}
    async with tenant_unit_of_work(uuid.UUID(o["org_id"])) as s:
        n = (await s.execute(select(AuditEvent).where(AuditEvent.entity_id == run_id,
                                                      AuditEvent.action == "echo"))).scalars().all()
    assert len(n) == 1 and n[0].job_id is not None


async def test_failed_job_goes_to_dead_letter_and_can_be_retried(client):
    o = await onboard(client)
    h = auth(o["token"], o["site_ids"][0])
    run_id = (await client.post("/api/v1/jobs/runs", headers=h,
                                json={"task": "system.echo", "payload": {"fail": True}})).json()["id"]
    await run_worker_until_idle()

    run = (await client.get(f"/api/v1/jobs/runs/{run_id}", headers=h)).json()
    assert run["status"] == "failed" and run["attempts"] == 3  # first run + 2 retries
    dead = (await client.get("/api/v1/jobs/dead-letter", headers=auth(o["token"]))).json()
    job = next(d for d in dead if d["args"].get("run_id") == run_id)
    r = await client.post(f"/api/v1/jobs/{job['id']}/retry", headers=auth(o["token"]))
    assert r.status_code == 202
    assert (await client.get(f"/api/v1/jobs/runs/{run_id}", headers=h)).json()["status"] == "queued"

    other = await onboard(client, "Other")
    assert (await client.post(f"/api/v1/jobs/{job['id']}/retry", headers=auth(other["token"]))).status_code == 404


async def _signed_up_user(email: str, name: str) -> str:
    """Insert a Better Auth user row, as the web app's sign-up would."""
    user_id = f"user_{uuid.uuid4().hex[:10]}"
    async with get_sessionmaker()() as s, s.begin():
        await s.execute(text(
            'INSERT INTO "user" (id, name, email, "emailVerified") VALUES (:id, :n, :e, false)'
        ), {"id": user_id, "n": name, "e": email})
    return user_id


async def test_owner_invites_site_member_and_claims_follow(client):
    o = await onboard(client, sites=2)
    site_a, site_b = o["site_ids"]
    email = f"chef.{uuid.uuid4().hex[:6]}@example.com"
    chef_id = await _signed_up_user(email, "Sam Okafor")

    r = await client.post("/api/v1/memberships", headers=auth(o["token"]),
                          json={"email": email, "role": "head_chef", "site_id": site_a})
    assert r.status_code == 201, r.text
    claims = (await client.get(f"/internal/auth/claims/{chef_id}", headers=CRON)).json()
    assert claims == {"organisation_id": o["org_id"], "org_role": None, "sites": {site_a: "head_chef"}}

    chef = make_token(chef_id, organisation_id=o["org_id"], sites=claims["sites"])
    sites = (await client.get("/api/v1/sites", headers=auth(chef))).json()
    assert [s["id"] for s in sites] == [site_a]  # sees only the site they are a member of
    members = (await client.get("/api/v1/memberships", headers=auth(o["token"]))).json()
    assert any(m["display_name"] == "Sam O." and m["role"] == "head_chef" for m in members)

    # An unknown email and a user from another organisation are refused.
    r = await client.post("/api/v1/memberships", headers=auth(o["token"]),
                          json={"email": "nobody@example.com", "role": "head_chef", "site_id": site_b})
    assert r.status_code == 404 and r.json()["code"] == "user_not_found"
    other = await onboard(client, "Northside Kitchens")
    r = await client.post("/api/v1/memberships", headers=auth(other["token"]),
                          json={"email": email, "role": "general_manager"})
    assert r.status_code == 409


async def test_org_wide_membership_covers_new_sites(client):
    o = await onboard(client, sites=3)
    claims = (await client.get(f"/internal/auth/claims/{o['user_id']}", headers=CRON)).json()
    assert set(claims["sites"]) == set(o["site_ids"]) and set(claims["sites"].values()) == {"owner"}
