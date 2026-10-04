# Tasks

- [x] OpenSpec artifacts (proposal, design, specs, tasks)
- [x] Migration 0007: recommendation_outcome, memory_entry (vector + ivfflat + GIN), note, schedule_run (RLS + grants)
- [x] `OutcomeEvaluator`: metric series, Theil–Sen counterfactual, verdicts, outcome rows, case memory, case close
- [x] Memory service: upsert per case and kind, on-demand embeddings via AIPort, retrieval score, recurring count
- [x] Investigation recalls similar cases (causal entities) and cites only them; recall adds evidence
- [x] Notes API joins memory; `/memory/search`; `/actions/{id}/outcome`
- [x] Dispatcher: `due_jobs` + `dispatch` with `schedule_run`; `/internal/dispatch`; simulator enqueues pipeline, outcomes and follow-ups
- [x] Seed: S7 operational record (closed case + memory) derived from the seeded PO/GRN/audit
- [x] Simulator: orders from the chosen supplier; same-day second PO; delivery after an early-posted invoice
- [x] Tests: unit (verdicts, counterfactual, memory score, due_jobs); integration `test_step6_flow4.py` (S7 recalled with score ≥ 0.5; +7 days improved; notes; dispatcher once per site/date)
