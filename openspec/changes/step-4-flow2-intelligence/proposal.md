# Proposal

## Why

OpsPilot MVP Flow 1 (invoice intake) is complete. Flow 2 must explain margin and revenue movements with deterministic evidence chains, not ad-hoc reports. The GM should see why GP fell and why Friday revenue dropped (seed scenarios S1/S2). The SRS worked example (Appendix B) is the acceptance target.

## What Changes

- Nightly pipeline: theoretical consumption, daily item cost/GP snapshots, detector registry, auto-investigation for warning/critical. Same-day related anomalies are folded into one incident (one case).
- MarginEngine (WAC-based recipe costing), repricing what-if, cost timeline with ingredient/supplier attribution.
- Pricing intelligence: supplier ranking (price, 90-day fill rate, lead time), switch candidate, period cost attribution by ingredient and supplier.
- Detector registry: v1 rules AR-01..AR-09 plus price_increase, stock_out, margin_decline, supplier_fill_rate and the FR-MNU-05 menu checks. Same-weekday median/MAD baselines, episode fingerprints/streaks, money severity, dismiss suppression.
- InvestigationEngine:
  - LMDI driver tree: orders x spend, mix/price split, item contributions grouped by shared ingredient, day x daypart concentration.
  - Hypothesis Library joining menu, recipes, stock ledger, PO/GRN/invoice, suppliers, weather, leakage, labour and cash.
  - SRS confidence formula, similar past cases from memory.
  - Narrative: Gemini A.3 narrative, Number Guard, deterministic template fallback.
- REST: `/menu/*` (items, cost-timeline, attribution, what-if), `/procurement/*`, `/suppliers/*`, `/anomalies` (+ dismiss), `/investigations/*`.
- Seed derives 120 days of cost snapshots through the real MarginEngine.
- Alembic `0005` (snapshots, anomalies, investigations) and `0007` (snapshot contribution, anomaly folding).

## Capabilities

### New Capabilities

- `margin-intelligence`: recipe costing, daily GP snapshots, repricing (FR-MNU-01/02/03/05/06/07).
- `pricing-intelligence`: price history, supplier ranking, cost attribution, switch rule (FR-PRC-01..04, 10).
- `anomaly-detection`: detector registry, baselines, fingerprints, severity, auto-investigate (FR-ANO-01..06).
- `root-cause-investigation`: driver tree, hypotheses, confidence, evidence chain, narrative (FR-RCA-01..08).
- `nightly-pipeline`: site-scoped orchestration and incident folding (FR-STK-03, FR-JOB-05 partial).

### Modified Capabilities

- (none: greenfield under the SRS)

## Impact

- `api/app/domain/{menu,pricing,detectors,investigation,intelligence}/*`, `api/migrations/versions/0005_*`, `0007_*`, `api/app/simulation/history.py`, `api/app/api/v1/{menu,procurement,anomalies,investigations}.py`, `api/tests/*`.
- OpenAPI client regeneration is deferred to Step 7.

## Review note (SRS fidelity correction)

The first implementation of this change was reworked after review against SRS v2.1:

- Recipe cost used the latest price instead of WAC.
- The detectors and investigation were stubs with hardcoded weights.
- Fill rate mixed units and future POs.
- Every nightly re-run duplicated anomalies and investigations.
- The exit test had been weakened to the stub's output (`stock_out`, GP 67.3%).

The specs below now state the SRS figures: 68.1% → 64.3%, `supplier_short_delivery` ≈0.86.
