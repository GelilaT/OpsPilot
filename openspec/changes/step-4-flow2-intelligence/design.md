# Design — Step 4 Flow 2

## Layering

- ORM lives in `app/domain/{menu,intelligence}`, pure rules in sibling modules (`lmdi`, `repricing`, `baseline`, `number_guard`, `confidence`), thin routers.
- Orchestration is `app/domain/intelligence/pipeline.py`, called by the `nightly.pipeline` job.
- No adapter imports in domain (import-linter).

## Costing (FR-MNU-02)

- `CostBook` loads recipes (all versions), site prices, per-ingredient WAC timelines (ledger receipts/openings) and price observations once per site.
- Item cost at a date = Σ qty_base_per_portion × WAC at end of that business day; never-received ingredients fall back to the latest observation.
- Snapshots store price ex VAT, cost, GP %, CM, units sold, total contribution and per-ingredient breakdown.
- The seed backfills every seeded day through the same code, so 28/90-day detectors work from day one.

S1 arithmetic for the Chicken Wrap (price 9.50 incl. VAT = 7.917 ex VAT):

| Date | Cost | GP | What changed |
|---|---|---|---|
| 4 Sep | 2.53 | 68.1% | — |
| 15 Sep | 2.59 | 67.3% | Tortilla wraps 0.28 → 0.34 |
| 2 Oct | 2.83 | 64.3% | Chicken WAC 6.70 → 7.90 |

Chicken explains 80% of the 28-day increase.

## Detectors (FR-ANO)

- The registry decorator registers each detector as `fn(ctx, run) -> [Detection]`.
- Baselines are the same weekday over `detection.baseline_weeks` (4), as median and MAD. Fewer than 3 points skips the detector and logs it.
- v1 rules keep their v1 triggers; AR-05/06 keep their v1 severity cap (info). Everything else uses weekly money severity (`detection.severity_*`).
- Fingerprints are built from detector + subject + episode start. A repeat within the detector's gap extends the episode (streak +1). Re-running the same date is idempotent. A dismissed fingerprint is suppressed for 7 days.
- `stock_out` reconstructs on-hand intraday: ledger opening + timed receipts − recipe use at each `sold_at`. The ingredient is out when what is left cannot serve a table (2 × the largest portion) and the dishes stop selling while the baseline expects sales.

## Incident folding

The pipeline orders anomalies by `PRIORITY` (`revenue_day`, then `daypart_revenue`, …). A root's same-day revenue-family anomalies (dayparts, product declines, stock-out, labour %, COGS) are folded into it. After investigating, any anomaly on an implicated entity is folded too: the ingredient's price increase and the dish's margin decline. Result: one Friday case, not fifteen.

## Investigation (FR-RCA)

Revenue driver tree:

- LMDI orders × spend, where the baseline is the mean of the same weekdays and the parts add up exactly.
- Spend split into price and mix per item, scaled to dR_spend.
- Item contributions grouped by shared ingredient; the focus group is the one holding most of the drop.
- Daypart concentration, flagged at ≥ 60%.

Margin anomalies use item cost attribution by ingredient and supplier.

Hypothesis Library weights (wₖ, calibrated on S2/S7; strengths sₖ are computed facts in 0..1):

| Evidence | Weight |
|---|---|
| short delivery vs PO (s = short % / 40%) | 0.70 |
| short delivery caused the stock-out (s = missing / need after stock-out) | 0.60 |
| stock-out explains the drop (s = focus share) | 0.75 |
| price explains item cost (s = share × materiality) | 0.90 |
| similar past case (s = memory score) | 0.35 |

- Confidence = (1 − Π(1 − wₖsₖ)) × timing × (1 − max refuting). Causes below `investigation.min_cause_confidence` (0.3) are hidden.
- A cause that is the mechanism of a deeper cause is shown as a chain: "Supplier short delivery → Ingredient stock-out".
- Refuted tests stay in the graph under "Ruled out" (weather factor, discounts and voids, covers per labour hour, demand range).

Narrative:

- Gemini narrates the evidence graph against the A.3 schema with node citations.
- The Number Guard checks every number in finding, evidence, cause and next-action text against the cited node's facts (rounded as written).
- The template is built from the same facts and is the fallback. It is stored as `narrative.text`; ranked causes, similar cases and guard violations sit beside it.

## Exit (S1/S2 on CP1)

After INV-4471 is posted and Friday 2 Oct is simulated:

- Friday dinner −29% (critical).
- Top cause `supplier_short_delivery` → `stock_out`, confidence 0.86.
- Evidence chain matches Appendix B: 12 kg vs 20 kg on the PO, 7.90 vs 6.70/kg, 95% of the drop in Friday dinner, Chicken Wrap 2.53 → 2.83, GP 68.1% → 64.3% (chicken 80%).
- Weather and discounts ruled out; 19 Sep recalled.
