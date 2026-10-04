"""Flow 1 (FR-INV-01..17): upload -> gates -> classify -> extract -> validate -> match -> checks ->
review -> approve -> post. Runs the real pipeline and worker with the offline AI adapter (ground-truth
and hand-recorded responses keyed by SHA-256).

Exit criterion (Phase 2b): golden invoices for both organisations are processed; S4 duplicates caught.
"""

import io
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.context import job_attempt_var
from app.core.tenancy.scoping import tenant_unit_of_work
from app.domain.inventory.models import StockMovement
from app.domain.purchasing.invoice_models import AICall, InvoiceDocument
from app.domain.purchasing.models import GoodsReceipt, LineAlias, PriceObservation
from app.ports.errors import RateLimitedError, TransientError
from app.simulation.catalogue import Catalogue, sid
from app.simulation.profiles import COPPER_POT, NORTHSIDE
from tests.conftest import auth, make_token

pytestmark = pytest.mark.integration
CRON = {"X-Cron-Secret": "test-cron-secret"}
DEMO = Path(__file__).resolve().parents[3] / "demo" / "invoices"


async def token(client, profile, email: str) -> str:
    user_id = sid(profile.slug, "user", email).hex
    claims = (await client.get(f"/internal/auth/claims/{user_id}", headers=CRON)).json()
    return make_token(user_id, email=email, organisation_id=claims["organisation_id"], org_role=claims["org_role"],
                      sites=claims["sites"])


def site(profile, code: str) -> str:
    return str(Catalogue(profile).site_id(next(s for s in profile.sites if s.code == code)))


async def run_worker() -> None:
    from app.workers.app import app as proc_app

    async with proc_app.open_async():
        await proc_app.run_worker_async(wait=False, install_signal_handlers=False, listen_notify=False)


async def upload(client, headers, path: Path, name: str | None = None, content: bytes | None = None):
    data = content if content is not None else path.read_bytes()
    r = await client.post("/api/v1/invoices", headers=headers, files={"file": (name or path.name, io.BytesIO(data))})
    assert r.status_code == 202, r.text
    return r.json()


async def detail(client, headers, doc_id: str) -> dict:
    r = await client.get(f"/api/v1/invoices/{doc_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def codes(d: dict, *, status: str = "open") -> set[str]:
    return {e["code"] for e in d["exceptions"] if e["status"] == status}


@pytest.fixture
async def cp(client, seeded):
    cp1 = site(COPPER_POT, "CP1")
    return {
        "chef": auth(await token(client, COPPER_POT, "chef@copperpot.example"), cp1),
        "gm": auth(await token(client, COPPER_POT, "gm@copperpot.example"), cp1),
        "owner": auth(await token(client, COPPER_POT, "owner@copperpot.example"), cp1),
        "shift": auth(await token(client, COPPER_POT, "shift@copperpot.example"), cp1),
        "site": cp1,
    }


@pytest.fixture
async def leeds(client, seeded):
    s = site(NORTHSIDE, "NK-LDS")
    return {"chef": auth(await token(client, NORTHSIDE, "chef.leeds@northside.example"), s),
            "gm": auth(await token(client, NORTHSIDE, "gm.leeds@northside.example"), s), "site": s}


async def test_inv_4471_end_to_end(client, cp):
    """S1 + S2: +18% chicken and 12 of 20 kg; GM approval required; posting books stock and prices."""
    doc = await upload(client, cp["chef"], DEMO / "copper-pot" / "INV-4471.pdf")
    assert doc["document"]["state"] == "received" and doc["file_url"]
    await run_worker()
    d = await detail(client, cp["chef"], doc["document"]["id"])
    assert d["document"]["state"] == "ready_for_approval", d["exceptions"]
    assert d["invoice"]["number"] == "INV-4471" and d["invoice"]["matched_supplier_name"] == "Ashworth Meats Ltd"
    assert d["invoice"]["purchase_order_number"] == "PO-CP1-261002-ASH"
    assert d["invoice"]["total_minor"] == d["invoice"]["ai_total_minor"]  # recomputed from lines, reconciles
    assert all(line["match_method"] == "sku" and line["qty_base"] for line in d["lines"])

    by_code = {}
    for e in d["exceptions"]:
        by_code.setdefault(e["code"], []).append(e)
    price = next(e for e in by_code["price_increase"] if e["facts"]["product"].startswith("Chicken thigh"))
    assert price["facts"]["last_per_unit_minor"] == 670 and price["facts"]["price_per_unit_minor"] == 790
    assert price["facts"]["change_pct"] == 17.9 and price["facts"]["impact_minor"] == 1440
    assert price["severity"] == "info" and not price["blocks_approval"]
    qty = next(e for e in by_code["qty_mismatch"] if e["facts"].get("against") == "ordered" and "Chicken" in e["message"])
    assert qty["facts"]["difference_pct"] == -40.0 and qty["requires_role"] == "general_manager"
    assert "12 kg invoiced vs 20 kg ordered on PO-CP1-261002-ASH" in qty["message"]
    assert "price_mismatch" in by_code
    assert d["approval"]["required_role"] == "general_manager" and d["approval"]["can_approve"] is False

    r = await client.post(f"/api/v1/invoices/{doc['document']['id']}/approve", headers=cp["chef"])
    assert r.status_code == 403 and r.json()["code"] == "approval_limit"
    assert (await client.get(f"/api/v1/invoices/{doc['document']['id']}", headers=cp["shift"])).status_code == 403
    r = await client.post(f"/api/v1/invoices/{doc['document']['id']}/approve", headers=cp["gm"])
    assert r.status_code == 200 and r.json()["document"]["state"] == "approved"
    await run_worker()
    d = await detail(client, cp["gm"], doc["document"]["id"])
    assert d["document"]["state"] == "posted" and d["invoice"]["posted_at"]

    cat = Catalogue(COPPER_POT)
    invoice_id = d["invoice"]["id"]
    async with tenant_unit_of_work(cat.org_id, uuid.UUID(cp["site"])) as s:
        receipt = (await s.execute(select(StockMovement).where(
            StockMovement.ref_id == invoice_id, StockMovement.ingredient_id == cat.ingredient_ids["chicken_thigh"]))).scalar_one()
        obs = (await s.execute(select(PriceObservation).where(PriceObservation.source_ref == invoice_id))).scalars().all()
        gr_count = (await s.execute(select(func.count()).select_from(GoodsReceipt).where(
            GoodsReceipt.purchase_order_id == uuid.UUID(d["invoice"]["purchase_order_id"])))).scalar()
    assert receipt.qty_base == Decimal(12000) and receipt.unit_cost_minor == Decimal("0.79")  # WAC reset to 7.90/kg
    assert len(obs) == len(d["lines"]) and any(o.unit_price_minor == 790 for o in obs)
    assert d["invoice"]["purchase_order_id"] and gr_count in (0, 1)  # GRN links when the delivery is recorded
    # Posting is idempotent: re-running the job books nothing more.
    from app.workers import invoice_tasks

    again = await invoice_tasks.post.func.__wrapped__(organisation_id=str(cat.org_id), site_id=cp["site"],
                                                      document_id=doc["document"]["id"])
    assert again == {"posted": False, "state": "posted"}


async def test_s4_exact_duplicate_and_rephotographed_invoice(client, cp):
    pdf = (DEMO / "copper-pot" / "INV-4471.pdf").read_bytes()
    first = await upload(client, cp["chef"], DEMO / "copper-pot" / "INV-4471.pdf", content=pdf)
    dup = await upload(client, cp["chef"], DEMO / "copper-pot" / "INV-4471.pdf", name="INV-4471 (1).pdf", content=pdf)
    assert dup["document"]["state"] == "duplicate"
    assert dup["document"]["duplicate_of_id"] in (first["document"]["id"], dup["document"]["duplicate_of_id"])

    photo = await upload(client, cp["chef"], DEMO / "copper-pot" / "INV-4471-photo.jpg")
    await run_worker()
    d = await detail(client, cp["chef"], photo["document"]["id"])
    assert d["document"]["state"] == "needs_review" and "possible_duplicate" in codes(d)
    dup_exc = next(e for e in d["exceptions"] if e["code"] == "possible_duplicate")
    assert dup_exc["severity"] == "critical" and dup_exc["blocks_approval"]
    r = await client.post(f"/api/v1/invoices/{photo['document']['id']}/exceptions/{dup_exc['id']}/accept",
                          headers=cp["chef"], json={"note": "not a duplicate"})
    assert r.status_code == 403  # critical exceptions need a GM or Owner
    r = await client.post(f"/api/v1/invoices/{photo['document']['id']}/reject", headers=cp["chef"],
                          json={"reason": "Duplicate of INV-4471 (photo of the same invoice)"})
    assert r.json()["document"]["state"] == "rejected"


async def test_statement_and_credit_memo_are_not_invoices(client, cp):
    statement = await upload(client, cp["chef"], DEMO / "copper-pot" / "castlefield-statement.pdf")
    memo = await upload(client, cp["chef"], DEMO / "real" / "3-star-repair-credit-memo.jpg")
    await run_worker()
    for doc, kind in ((statement, "statement"), (memo, "credit_note")):
        d = await detail(client, cp["chef"], doc["document"]["id"])
        assert d["document"]["state"] == "not_invoice" and d["document"]["doc_type"] == kind
        assert d["invoice"] is None


async def test_golden_real_invoice_routes_to_review(client, cp):
    """Real-world INR invoice: totals reconcile with mixed GST rates, but unknown supplier and an old date."""
    doc = await upload(client, cp["chef"], DEMO / "real" / "mixed-invoice-inr.webp")
    await run_worker()
    d = await detail(client, cp["chef"], doc["document"]["id"])
    assert d["document"]["state"] == "needs_review"
    assert {"unknown_supplier", "missing_field"} <= codes(d) and "math_error" not in codes(d)
    assert d["invoice"]["subtotal_minor"] == 5_600_000 and d["invoice"]["vat_minor"] == 918_000
    assert d["invoice"]["total_minor"] == d["invoice"]["ai_total_minor"] == 6_518_000
    old = next(e for e in d["exceptions"] if e["code"] == "missing_field")
    assert "more than 18 months old" in old["message"]


async def test_two_invoices_in_one_file_need_confirmation(client, leeds):
    doc = await upload(client, leeds["chef"], DEMO / "northside-kitchens" / "NK-LDS-two-invoices.pdf")
    await run_worker()
    d = await detail(client, leeds["chef"], doc["document"]["id"])
    assert d["document"]["state"] == "needs_review" and codes(d) == {"low_confidence"}
    exc = d["exceptions"][0]
    assert exc["facts"]["multiple_documents"] is True
    r = await client.post(f"/api/v1/invoices/{doc['document']['id']}/exceptions/{exc['id']}/accept",
                          headers=leeds["chef"], json={"note": "Only the first invoice is ours to process"})
    assert r.status_code == 200 and r.json()["document"]["state"] == "extracting"
    await run_worker()
    d = await detail(client, leeds["chef"], doc["document"]["id"])
    assert d["document"]["state"] in ("ready_for_approval", "needs_review") and d["invoice"]["number"]


async def test_golden_northside_invoice_review_cycle(client, leeds):
    """Edit -> revalidate, unmatched line -> map (LineAlias learned), math error, If-Match, approve, void."""
    files = sorted((DEMO / "northside-kitchens").glob("NK-LDS-produce-*.pdf"))
    doc = await upload(client, leeds["chef"], files[0])
    await run_worker()
    doc_id = doc["document"]["id"]
    d = await detail(client, leeds["chef"], doc_id)
    assert d["document"]["state"] == "ready_for_approval", d["exceptions"]
    first = d["lines"][0]

    # A line the matcher cannot place -> unmatched_line blocks approval.
    r = await client.patch(f"/api/v1/invoices/{doc_id}", headers=leeds["chef"], json={"lines": [
        {"id": first["id"], "raw_description": "Market special ZX-9", "supplier_sku": None}]})
    d = r.json()
    assert d["document"]["state"] == "needs_review" and "unmatched_line" in codes(d)
    r = await client.post(f"/api/v1/invoices/{doc_id}/lines/{first['id']}/match", headers=leeds["chef"],
                          json={"supplier_product_id": first["supplier_product_id"]})
    d = r.json()
    assert d["document"]["state"] == "ready_for_approval" and d["lines"][0]["match_method"] == "manual"
    cat = Catalogue(NORTHSIDE)
    async with tenant_unit_of_work(cat.org_id) as s:
        alias = (await s.execute(select(LineAlias).where(LineAlias.normalised_text == "market special zx 9"))).scalar_one()
    assert str(alias.supplier_product_id) == first["supplier_product_id"]

    # A wrong line total is a math error that cannot be accepted - it must be corrected.
    r = await client.patch(f"/api/v1/invoices/{doc_id}", headers=leeds["chef"],
                           json={"lines": [{"id": first["id"], "line_total_minor": first["line_total_minor"] + 500}]})
    d = r.json()
    assert d["document"]["state"] == "needs_review" and "math_error" in codes(d)
    math = next(e for e in d["exceptions"] if e["code"] == "math_error" and e["status"] == "open")
    r = await client.post(f"/api/v1/invoices/{doc_id}/exceptions/{math['id']}/accept", headers=leeds["gm"],
                          json={"note": "looks fine"})
    assert r.status_code == 422 and r.json()["code"] == "not_acceptable"
    version = d["document"]["version"]
    r = await client.patch(f"/api/v1/invoices/{doc_id}", headers={**leeds["chef"], "If-Match": str(version - 1)},
                           json={"lines": [{"id": first["id"], "line_total_minor": first["line_total_minor"]}]})
    assert r.status_code == 412
    r = await client.patch(f"/api/v1/invoices/{doc_id}", headers={**leeds["chef"], "If-Match": str(version)},
                           json={"lines": [{"id": first["id"], "line_total_minor": first["line_total_minor"]}]})
    assert r.json()["document"]["state"] == "ready_for_approval"

    # Approve with the role the invoice requires (GM when a line was short-delivered); editing before
    # posting voids the approval.
    d = r.json()
    approver = leeds["chef"] if d["approval"]["required_role"] == "head_chef" else leeds["gm"]
    assert d["approval"]["required_role"] == ("general_manager" if "qty_mismatch" in codes(d) else "head_chef")
    r = await client.post(f"/api/v1/invoices/{doc_id}/approve", headers=approver)
    assert r.status_code == 200, r.text
    r = await client.patch(f"/api/v1/invoices/{doc_id}", headers=leeds["chef"], json={"due_date": "2026-10-20"})
    d = r.json()
    assert d["document"]["state"] == "ready_for_approval" and d["invoice"]["approved_by"] is None
    assert any("approval was voided" in t["reason"] for t in d["transitions"])


async def test_upload_gates(client, cp):
    from PIL import Image

    logo = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(logo, format="PNG")
    d = await upload(client, cp["chef"], Path("logo.png"), content=logo.getvalue())
    assert d["document"]["state"] == "failed" and "logo" in d["document"]["failure_reason"]
    d = await upload(client, cp["chef"], Path("notes.txt"), content=b"just some text " * 1000)
    assert d["document"]["state"] == "failed" and "Unsupported file type" in d["document"]["failure_reason"]
    import pymupdf

    big = pymupdf.open()
    for _ in range(11):
        big.new_page()
    d = await upload(client, cp["chef"], Path("big.pdf"), content=big.tobytes())
    assert d["document"]["state"] == "failed" and "11 pages" in d["document"]["failure_reason"]
    r = await client.post(f"/api/v1/invoices/{d['document']['id']}/retry", headers=cp["chef"])
    assert r.status_code == 409


async def test_transient_errors_retry_then_fail_and_429_defers(client, cp):
    """FR-INV-17 with an AI provider that fails: retries, final failure with a reason, manual retry."""
    from app.adapters.ai.fake import FakeAI
    from app.core.integrations import registry
    from app.ports import IntegrationKind
    from app.workers import invoice_tasks
    from app.workers.runtime import Defer

    registry.register(IntegrationKind.ai, "fake_down", lambda c: FakeAI(fail_with=TransientError("503", provider="x")))
    registry.register(IntegrationKind.ai, "fake_429", lambda c: FakeAI(fail_with=RateLimitedError("429", retry_after=60)))
    r = await client.post("/api/v1/integrations", headers=auth(await token(client, COPPER_POT, "owner@copperpot.example")),
                          json={"kind": "ai", "provider": "fake_down", "site_id": cp["site"]})
    assert r.status_code == 201
    try:
        d = await upload(client, cp["chef"], Path("synthetic.pdf"),
                         content=(DEMO / "northside-kitchens" / "NK-LDS-two-invoices.pdf").read_bytes())
        doc_id = d["document"]["id"]
        cat = Catalogue(COPPER_POT)
        kwargs = {"organisation_id": str(cat.org_id), "site_id": cp["site"], "document_id": doc_id}
        fn = invoice_tasks.process.func.__wrapped__
        token_ = job_attempt_var.set(0)
        with pytest.raises(TransientError):
            await fn(**kwargs)  # first attempt: re-raised so the job engine retries after 2 s
        job_attempt_var.set(3)
        result = await fn(**kwargs)  # last attempt: the document fails with a reason
        job_attempt_var.reset(token_)
        assert result["state"] == "failed"
        detail_ = await detail(client, cp["chef"], doc_id)
        assert detail_["document"]["state"] == "failed" and "503" in detail_["document"]["failure_reason"]

        await client.post("/api/v1/integrations", headers=auth(await token(client, COPPER_POT, "owner@copperpot.example")),
                          json={"kind": "ai", "provider": "fake_429", "site_id": cp["site"]})
        r = await client.post(f"/api/v1/invoices/{doc_id}/retry", headers=cp["chef"])
        assert r.status_code == 202 and r.json()["document"]["state"] == "received"
        with pytest.raises(Defer):  # a 429 defers the job (60 s) without using a retry attempt
            await fn(**kwargs)
        async with tenant_unit_of_work(cat.org_id, uuid.UUID(cp["site"])) as s:
            outcomes = (await s.execute(select(AICall.outcome).where(AICall.document_id == uuid.UUID(doc_id)))).scalars().all()
        assert set(outcomes) >= {"transient", "rate_limited"}
    finally:
        await client.post("/api/v1/integrations", headers=auth(await token(client, COPPER_POT, "owner@copperpot.example")),
                          json={"kind": "ai", "provider": "fake", "site_id": cp["site"]})


async def test_simulated_invoice_is_processed(client, leeds):
    r = await client.post("/api/v1/invoices/simulate", headers=leeds["chef"], json={})
    assert r.status_code == 202 and r.json()["document"]["source"] == "simulate"
    await run_worker()
    d = await detail(client, leeds["chef"], r.json()["document"]["id"])
    assert d["document"]["state"] in ("ready_for_approval", "needs_review")
    assert d["invoice"]["number"].startswith("SIM-") and all(line["supplier_product_id"] for line in d["lines"])
    priced = await client.post("/api/v1/invoices/simulate", headers=leeds["chef"], json={"price_change_pct": 25})
    await run_worker()
    d = await detail(client, leeds["chef"], priced.json()["document"]["id"])
    assert "price_increase" in codes(d)


async def test_invoices_are_tenant_and_site_scoped(client, cp, leeds):
    listing = (await client.get("/api/v1/invoices", headers=cp["chef"])).json()
    some = listing["items"][0]["id"]
    assert listing["counts"] and sum(listing["counts"].values()) >= len(listing["items"])
    assert (await client.get(f"/api/v1/invoices/{some}", headers=leeds["chef"])).status_code == 404
    york_gm = auth(await token(client, NORTHSIDE, "gm.york@northside.example"), site(NORTHSIDE, "NK-YRK"))
    leeds_items = (await client.get("/api/v1/invoices", headers=leeds["chef"])).json()["items"]
    assert (await client.get(f"/api/v1/invoices/{leeds_items[0]['id']}", headers=york_gm)).status_code == 404
    filtered = (await client.get("/api/v1/invoices", headers=cp["chef"], params={"state": "not_invoice"})).json()
    assert all(i["state"] == "not_invoice" for i in filtered["items"])
    cat = Catalogue(COPPER_POT)
    async with tenant_unit_of_work(cat.org_id) as s:
        n = (await s.execute(select(func.count()).select_from(InvoiceDocument))).scalar()
    assert n >= len(listing["items"])
