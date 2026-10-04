# Tasks

## 1. Schema and models

- [x] Alembic 0005 + ORM models; RLS list
- [x] Alembic 0007: snapshot units/total contribution, anomaly `parent_id` / `investigated_severity`
- [x] OpenSpec artifacts (proposal, specs, design, tasks)

## 2. Margin and pricing domain

- [x] WAC-based `CostBook`, `snapshot_range`, seed backfill (`simulation/history.py`)
- [x] `repricing.py` (FR-MNU-06) + `/menu/items/{id}/what-if`; item attribution + `/menu/items/{id}/attribution`
- [x] `supplier_ranking.py`: value-weighted fill rate on due POs (invoiced qty when no GRN), switch candidate
- [x] `attribution.py`: (current − previous price) × current qty, by ingredient and supplier

## 3. Detection and investigation

- [x] Detector registry: AR-01..09, price_increase, stock_out, margin_decline, supplier_fill_rate, MNU-05 checks
- [x] Episode fingerprints/streaks, money severity (AR-05/06 capped at info), dismiss suppression
- [x] Intraday stock-out reconstruction
- [x] LMDI split (mix/price/items), concentration; Hypothesis Library; confidence; similar cases
- [x] Number Guard on all narrative fields; template fallback; investigation versions

## 4. Jobs and API

- [x] `domain/intelligence/pipeline.py` with incident folding; `nightly.pipeline` job; simulator enqueues it
- [x] REST: menu, procurement, suppliers, anomalies (+ dismiss), investigations (+ versions, rerun GM+)

## 5. Tests

- [x] Unit/property: LMDI parts and item effects sum, repricing (Appendix B), Number Guard, confidence, baselines
- [x] Integration `test_step4_flow2.py`: GP 68.1 → 64.3, attribution 80%, what-if 9.95; cause ≈0.86 with the full evidence chain; folding + idempotent re-run; supplier comparison; dismiss suppression

## 6. SRS fidelity corrections (review of the first implementation)

- [x] Replace the latest-price costing with WAC; fix the 67.3% acceptance figure to the SRS 68.1% → 64.3%
- [x] Replace the stub investigation (hardcoded weights, every-row stock-out, any-price increase) with the Hypothesis Library
- [x] Stop duplicate anomalies/investigations on re-runs; fix fill-rate unit mixing and future POs
- [x] Restore the exit test to the SRS figures (it had been weakened to the stub's output)
