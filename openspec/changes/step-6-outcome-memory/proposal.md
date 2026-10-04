# Proposal

## Why

Flow 4 closes the agent loop (Detect → Investigate → Recommend → Approve → Execute → **Measure**). Each executed recommendation is measured against a counterfactual, and the result is remembered so the next similar case can cite it (SRS MVP Flow 4, scenario S7).

## What Changes

- `OutcomeEvaluator` (06:00):
  - for recommendations in `follow_up` whose follow-up date has passed, measure the success metric before and after execution;
  - counterfactual = pre-period Theil–Sen trend projected forward; verdict improved / no_change / worsened per FR-ACT-07;
  - store a `recommendation_outcome`, move the recommendation to `outcome_measured`, write memory, close the case when nothing is pending.
- Operational memory:
  - `memory_entry` (site-scoped subjects, cause code, templated summary, actions, outcome, notes, pgvector embedding with an ivfflat cosine index), one per case and kind;
  - written when an outcome is measured and when a case closes by rejection or expiry.
- Retrieval: candidates share a subject or cause within 365 days; score = 0.5 Jaccard + 0.3 cosine + 0.2 recency (half-life 60 days); top 3 with score ≥ 0.5.
  - Embeddings come from the site's AIPort (Gemini, or the fake in tests). They are computed on demand; when the provider is unavailable, retrieval runs on structure only.
  - The investigation cites only retrieved entries (FR-MEM-05), and a recall adds evidence to the cause it shares.
- Notes (`note`) on investigations, recommendations or cases join the case's memory and clear its embedding for re-embedding (FR-MEM-02).
- Dispatcher (FR-JOB-05): POST `/internal/dispatch` every 5 minutes computes due schedules in each site's timezone (pipeline 02:00 for the previous business date, outcomes 06:00, follow-ups 16:00) and enqueues each once per site, job and local date (`schedule_run`). Simulated sites get the same jobs from `simulator.next_day`.
- The seed derives the S7 record (19 Sep short delivery from Ashworth Meats, resolved by raising the par to 18 kg) as a closed case with its memory entry. The simulator orders from the site's chosen supplier, and an invoice posted before delivery still gets its goods receipt.

## Capabilities

### New Capabilities

- `outcome-measurement`: counterfactual effect and verdict per success metric (FR-ACT-06/07).
- `operational-memory`: memory entries, notes, retrieval and citation rules (FR-MEM-01/02/03/05).
- `job-scheduling`: per-timezone dispatcher with unique schedule runs (FR-JOB-05).

## Impact

- `api/migrations/0007_*` (recommendation_outcome, memory_entry + vector index, note, schedule_run).
- `api/app/domain/outcomes/*`, `domain/memory/*`, `core/schedules.py`, `api/v1/{memory,internal,actions}.py`.
- `workers/nightly_tasks.py`, `simulation/{history,state,world,persist}.py`; tests.
