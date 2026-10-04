"""Flow 4 (FR-ACT-06/07, FR-MEM-01/02/03/05, FR-JOB-05): outcome measurement and operational memory.

Exit criterion (plan Step 6): simulating +7 days gives "improved"; S7 is recalled in the S2 investigation.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from app.core.schedules import ScheduleRun
from app.core.tenancy.scoping import system_unit_of_work, tenant_unit_of_work
from app.domain.memory.models import MemoryEntry
from app.simulation.catalogue import Catalogue
from app.simulation.profiles import COPPER_POT
from tests.integration.scenario import approve, business_date, demo_friday, simulate_day
from tests.integration.test_step3_invoices import CRON

pytestmark = pytest.mark.integration


async def test_s7_recalled_in_s2_investigation(client, copper):
    """FR-MEM-03/05: the 19 Sep short delivery is retrieved (score >= 0.5) and is the only history cited."""
    case = await demo_friday(client, copper)
    inv = (await client.get(f"/api/v1/investigations/{case['investigation_id']}", headers=copper["gm"])).json()
    similar = inv["narrative"]["similar_cases"]
    assert similar and similar[0]["date"] == "2026-09-19" and similar[0]["score"] >= 0.5
    assert similar[0]["cause_code"] == "supplier_short_delivery" and similar[0]["verdict"] == "improved"
    memory_nodes = [n for n in inv["graph"]["nodes"] if n["kind"] == "memory"]
    assert [n["facts"]["memory_id"] for n in memory_nodes] == [s["memory_id"] for s in similar]
    texts = [e["text"] for e in inv["narrative"]["text"]["evidence"] if e["node_id"].startswith("memory:")]
    assert texts and all("19 Sep" in t for t in texts)
    assert "memory:1" in inv["narrative"]["causes"][0]["node_ids"]  # the recall supports the top cause

    hits = (await client.get("/api/v1/memory/search", headers=copper["gm"], params={
        "q": "chicken short delivery", "cause_code": "supplier_short_delivery",
        "subject": [f"ingredient:{Catalogue(COPPER_POT).ingredient_ids['chicken_thigh']}"]})).json()
    assert hits and hits[0]["date"] == "2026-09-19" and 0.5 <= hits[0]["score"] <= 1


async def test_seven_days_later_outcome_improved(client, copper):
    """Exit: approve the switch, simulate +7 days; the 06:00 evaluation measures chicken cost per kg against
    the counterfactual: improved, written to memory with the case."""
    case = await demo_friday(client, copper)
    switch = await approve(client, copper, "supplier_switch")
    await approve(client, copper, "par_level_change")
    while await business_date(client, copper) < datetime(2026, 10, 9).date():
        await simulate_day(client, copper)

    switch = (await client.get(f"/api/v1/actions/{switch['id']}", headers=copper["gm"])).json()
    assert switch["status"] == "outcome_measured", switch["status"]
    outcome = (await client.get(f"/api/v1/actions/{switch['id']}/outcome", headers=copper["gm"])).json()
    assert outcome["metric"] == "cost_per_base_unit" and outcome["verdict"] == "improved", outcome
    assert float(outcome["effect"]) < 0 and abs(float(outcome["effect"])) >= abs(float(outcome["expected_effect"])) / 2
    assert outcome["post_start"] == "2026-10-03" and outcome["post_end"] == "2026-10-09"

    detail = (await client.get(f"/api/v1/cases/{case['case_id']}", headers=copper["gm"])).json()
    assert any(o["verdict"] == "improved" for o in detail["outcomes"])
    memory = next(m for m in detail["memory"] if m["kind"] == "outcome")
    assert memory["outcome"]["verdict"] == "improved" and "Switch chicken thigh" in memory["summary"]
    timeline = [e["kind"] for e in (await client.get(f"/api/v1/cases/{case['case_id']}/timeline",
                                                     headers=copper["gm"])).json()]
    assert "outcome_measured" in timeline and "memory_written" in timeline


async def test_notes_join_memory(client, copper):
    """FR-MEM-02: a manager's note joins the case memory (and is re-embedded)."""
    case = await demo_friday(client, copper)
    r = await client.post("/api/v1/notes", headers=copper["gm"], json={
        "target_type": "investigation", "target_id": case["investigation_id"],
        "text": "Ashworth said their Friday van was short-staffed."})
    assert r.status_code == 201 and r.json()["case_id"] == case["case_id"]
    cat = Catalogue(COPPER_POT)
    async with tenant_unit_of_work(cat.org_id, uuid.UUID(copper["site"])) as s:
        entries = (await s.execute(select(MemoryEntry).where(
            MemoryEntry.case_id == uuid.UUID(case["case_id"])))).scalars().all()
    for entry in entries:
        assert "short-staffed" in (entry.notes or "") and entry.embedding is None
    timeline = (await client.get(f"/api/v1/cases/{case['case_id']}/timeline", headers=copper["gm"])).json()
    assert any(e["kind"] == "note" for e in timeline)


async def test_dispatcher_enqueues_once_per_site_and_date(client, copper):
    """FR-JOB-05: the 5-minute tick enqueues each due job once per site, job and local date."""
    from app.core.schedules import dispatch

    noon = datetime(2026, 10, 4, 15, 30, tzinfo=UTC)  # 16:30 in London: pipeline, outcomes, brief and follow-ups due
    async with system_unit_of_work() as s:
        first = await dispatch(s, noon, include_simulated=True)
    async with system_unit_of_work() as s:
        second = await dispatch(s, noon, include_simulated=True)
        runs = (await s.execute(select(ScheduleRun).where(ScheduleRun.local_date == noon.date()))).scalars().all()
    assert {q["job"] for q in first} == {"nightly.pipeline", "outcomes.evaluate", "brief.daily", "followups.run"}
    assert second == [] and len(runs) == len(first)
    nightly = next(q for q in first if q["job"] == "nightly.pipeline")
    assert nightly["business_date"] == "2026-10-03"  # the night after the previous trading day

    r = await client.post("/internal/dispatch", headers=CRON)  # wall clock; simulated sites are skipped
    assert r.status_code == 200 and isinstance(r.json()["queued"], list)
    ids = [q["job_id"] for q in first + r.json()["queued"] if q.get("job_id")]
    async with system_unit_of_work() as s:  # the tick's jobs are not part of the demo timeline
        await s.execute(text("DELETE FROM procrastinate_jobs WHERE id = ANY(:ids)"), {"ids": ids})
