"""Pure rules behind Flows 2-4: repricing, LMDI, confidence, Number Guard, outcome verdicts, the
recommendation state chart, case status, memory scoring and the dispatcher's due times."""

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.core.schedules import due_jobs
from app.core.tenancy.config import Schedules
from app.domain.actions.impact import par_level_change, recompute, supplier_switch
from app.domain.actions.rules import TERMINAL, TRANSITIONS, can_transition, derive_case_status
from app.domain.detectors.baseline import Baseline
from app.domain.investigation.confidence import cause_confidence
from app.domain.investigation.hypotheses import weather_factor
from app.domain.investigation.number_guard import check_narrative, numbers_in, violations
from app.domain.memory.service import jaccard, recency, score
from app.domain.menu.lmdi import concentration, decompose_revenue, split_spend
from app.domain.menu.repricing import round_to_endings, suggest
from app.domain.outcomes.evaluator import counterfactual, theil_sen, verdict

D = Decimal


# ---- FR-MNU-06 repricing (Appendix B: Chicken Wrap 9.50 -> 9.95 restores GP to 65.9%) -------------------
def test_repricing_appendix_b():
    r = suggest(cost_minor=283, current_gross_minor=950, vat_rate=D("0.2"), target_gp=D("0.65"), endings=[95, 50, 0],
                weekly_units=D("146.7"))
    assert r.suggested_gross_minor == 995 and r.suggested_gp_pct == D("65.9") and r.current_gp_pct == D("64.3")
    assert r.weekly_gp_impact_minor == 5501  # +55 per week at current volume
    assert r.weekly_gp_impact_lower_volume_minor == 1495  # +15 per week at -5% volume


def test_price_endings_round_up():
    assert round_to_endings(971, [95, 50, 0]) == 995
    assert round_to_endings(1001, [95, 50, 0]) == 1050
    assert round_to_endings(1000, [95, 50, 0]) == 1000
    assert round_to_endings(996, [95]) == 1095


# ---- LMDI (SRS 4.3) ------------------------------------------------------------------------------------
@given(o0=st.integers(50, 400), s0=st.integers(1000, 6000), o1=st.integers(50, 400), s1=st.integers(1000, 6000),
       units=st.lists(st.tuples(st.integers(0, 80), st.integers(0, 80), st.integers(300, 2000), st.integers(300, 2000)),
                      min_size=1, max_size=12))
def test_lmdi_parts_and_item_effects_sum_exactly(o0, s0, o1, s1, units):
    total, d_orders, d_spend = decompose_revenue(D(o0), D(s0), D(o1), D(s1))
    assert abs(d_orders + d_spend - total) < D("1e-9")  # exact up to Decimal precision
    base = {uuid.UUID(int=i): (D(u0), D(u0 * p0)) for i, (u0, _, p0, _) in enumerate(units)}
    now = {uuid.UUID(int=i): (D(u1), D(u1 * p1)) for i, (_, u1, _, p1) in enumerate(units)}
    split = split_spend(d_spend, D(o0), D(o1), base, now)
    if any(i.contribution for i in split.items):
        assert abs(sum(i.contribution for i in split.items) - d_spend) < D("0.0001")
        assert abs(split.price_effect + split.mix_effect - d_spend) < D("1e-9")


def test_concentration_of_the_drop():
    seg, share = concentration({"lunch": D(-50), "dinner": D(-1600), "late": D(-30), "afternoon": D(20)})
    assert seg == "dinner" and share > D("0.6")
    assert concentration({"lunch": D(10)}) == (None, D(0))


# ---- FR-RCA-05 confidence --------------------------------------------------------------------------------
def test_confidence_formula():
    # (1 - (1 - 0.7)(1 - 0.6 x 0.625)(1 - 0.35 x 0.72)) x 1 x 1 = 0.86 (the S2 calibration)
    assert cause_confidence([(D("0.70"), D(1)), (D("0.60"), D("0.625")), (D("0.35"), D("0.72"))]).quantize(
        D("0.01")) == D("0.86")
    assert cause_confidence([(D("0.7"), D(1))], timing=D("0.5")) == D("0.35")
    assert cause_confidence([(D("0.7"), D(1))], max_refuting=D("0.6")) == D("0.28")  # below 0.3: hidden
    assert cause_confidence([]) == 0


def test_weather_factor_bands():
    assert weather_factor(D(18), D("1.7")) == D("1.00")
    assert weather_factor(D(18), D(20)) == D("0.88")
    assert weather_factor(D(25), D(0)) == D("1.08")


# ---- FR-RCA-07 Number Guard -------------------------------------------------------------------------------
def test_numbers_in_text():
    assert numbers_in("Revenue 7,410 vs 9,040 (-18.0%) at 18:40") == [
        (D(7410), 0), (D(9040), 0), (D("18.0"), 1), (D(18), 0), (D(40), 0)]


def test_number_guard_accepts_rounded_facts_and_rejects_invented_numbers():
    nodes = [{"id": "rev", "facts": {"observed": 7410.12, "deviation_pct": -18.04, "out_at": "18:40"}},
             {"id": "cause:x", "facts": {"confidence": 0.8601}}]
    assert violations("Friday revenue 7,410 (-18.0%), out at 18:40.", nodes) == []
    assert violations("Revenue fell 25% because of rain.", nodes) == ["25"]
    narrative = {"finding": "Revenue 7,410.", "next_action": "Check orders.",
                 "evidence": [{"node_id": "rev", "text": "Down 18.0%"}, {"node_id": "nope", "text": "x"}],
                 "causes": [{"cause_code": "x", "confidence_node_id": "cause:x", "text": "confidence 0.86 or 0.91"}]}
    problems = check_narrative(narrative, nodes)
    assert "evidence cites unknown node 'nope'" in problems and "cause cause:x: 0.91" in problems
    assert len(problems) == 2


# ---- Baselines and impact --------------------------------------------------------------------------------
def test_baseline_median_and_mad():
    b = Baseline.of([D(9648), D(10915), D(7986), D(8192)])
    assert b.n == 4 and b.median == D("8920") and b.sigma > 0 and b.z(D(8920)) == 0


def test_impact_formulas():
    assert supplier_switch(D(118_000), D("0.071")) == 8378  # 118 kg/week x 0.71/kg
    assert par_level_change(52_700, D("0.5"), D(18_000), D(28_000), D("0.79")) == 26_311
    impact, inputs = recompute("price_review", {"suggested_gross_minor": 1050}, {
        "cost_minor": 283, "current_gross_minor": 950, "vat_rate": 0.2, "weekly_units": 146.7})
    assert impact > 5501 and inputs["impact_lower_volume_minor"] < impact


# ---- FR-ACT-03 state chart and FR-ACT-11 case status -------------------------------------------------------
def test_state_chart():
    assert can_transition("proposed", "approved") and can_transition("follow_up", "outcome_measured")
    assert not can_transition("approved", "proposed") and not can_transition("rejected", "approved")
    assert all(not TRANSITIONS[s] for s in TERMINAL)


def test_case_status_is_derived():
    assert derive_case_status(investigated=False, rec_statuses=[]) == "detected"
    assert derive_case_status(investigated=True, rec_statuses=["proposed", "follow_up"]) == "awaiting_approval"
    assert derive_case_status(investigated=True, rec_statuses=["approved", "rejected"]) == "executing"
    assert derive_case_status(investigated=True, rec_statuses=["follow_up", "rejected"]) == "monitoring"
    assert derive_case_status(investigated=True, rec_statuses=["outcome_measured", "rejected"]) == "closed"


# ---- FR-ACT-07 outcome -------------------------------------------------------------------------------------
def test_outcome_verdicts():
    pre = [D("0.67")] * 13 + [D("0.79")]
    assert theil_sen(pre) == 0 and counterfactual(pre, 7) == D("0.79")
    assert verdict(D("-0.06"), D("-0.071"), D("0.03")) == "improved"
    assert verdict(D("-0.02"), D("-0.071"), D("0.03")) == "no_change"
    assert verdict(D("0.05"), D("-0.071"), D("0.03")) == "worsened"
    assert counterfactual([D(1), D(2), D(3)], 2) == D("4.5")  # trend projected over the post window


# ---- FR-MEM-03 memory score --------------------------------------------------------------------------------
def test_memory_score():
    assert jaccard({"a", "b"}, {"a", "b"}) == 1 and jaccard({"a"}, {"b"}) == 0
    assert recency(0) == 1 and recency(60) == D("0.5")
    s = score(D(1), D("0.16"), 13)  # the S7 recall: same ingredient and supplier, 13 days old
    assert D("0.5") <= s <= 1


# ---- FR-JOB-05 dispatcher -----------------------------------------------------------------------------------
def test_due_jobs_follow_site_time_zones():
    org, london, ny = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sites = [(org, london, "Europe/London", Schedules()), (org, ny, "America/New_York", Schedules())]
    at = datetime(2026, 10, 4, 5, 30, tzinfo=UTC)  # 06:30 London, 01:30 New York
    due = {(d.site_id, d.job): d for d in due_jobs(at, sites)}
    assert (london, "nightly.pipeline") in due and (london, "outcomes.evaluate") in due
    assert (london, "followups.run") not in due and not any(s == ny for s, _ in due)
    assert due[(london, "nightly.pipeline")].business_date == date(2026, 10, 3)
    assert Schedules().follow_ups == time(16, 0)


def test_briefs_are_due_after_their_local_time_and_recap_only_on_its_weekday():
    org, site = uuid.uuid4(), uuid.uuid4()
    sites = [(org, site, "Europe/London", Schedules())]
    monday = datetime(2026, 10, 5, 7, 30, tzinfo=UTC)  # 08:30 BST on a Monday
    due = {d.job: d for d in due_jobs(monday, sites)}
    assert "brief.daily" in due and "brief.weekly" in due
    assert due["brief.daily"].business_date == date(2026, 10, 4) and due["brief.weekly"].business_date == date(2026, 10, 4)
    assert "brief.weekly" not in {d.job for d in due_jobs(datetime(2026, 10, 5, 6, 30, tzinfo=UTC), sites)}  # 07:30 < 08:00
    tuesday = {d.job for d in due_jobs(datetime(2026, 10, 6, 12, 0, tzinfo=UTC), sites)}
    assert "brief.daily" in tuesday and "brief.weekly" not in tuesday
