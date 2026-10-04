# root-cause-investigation

## ADDED Requirements

### Requirement: Driver tree and evidence chain

The system SHALL build each investigation from:

- the anomaly, its window and same-weekday baseline windows;
- an LMDI decomposition (orders × spend; mix and price; item contributions grouped by shared ingredient) whose parts sum to the total;
- day × daypart concentration, reported as concentrated at ≥ 60%;
- hypothesis tests joining recipes, the stock ledger, PO/GRN/invoices, suppliers, weather, discounts and voids, labour and cash-ups.

It SHALL output a finding, an ordered evidence chain with computed facts, causes ranked by confidence, recommendation drafts and similar past cases.

#### Scenario: S2 short delivery root cause

- **WHEN** investigating the Friday 2026-10-02 drop after INV-4471 delivered 12 kg against a 20 kg PO
- **THEN** the top cause SHALL be `supplier_short_delivery` with chain `supplier_short_delivery → stock_out` and confidence 0.86 (±0.02)
- **AND** the evidence SHALL include: the PO shortfall (40%) and price (7.90 vs 90-day median 6.70); 95% of the drop in Friday dinner with no chicken dishes sold after the stock-out; Chicken Wrap 2.53 → 2.83 with GP 68.1% → 64.3%; weather and discounts ruled out

### Requirement: Confidence formula

Confidence per cause SHALL be (1 − Π(1 − weight × strength)) × timing (1 when the cause precedes the effect, otherwise 0.5) × (1 − largest refuting weight); causes below 0.3 are hidden.

#### Scenario: Timing

- **WHEN** a short delivery arrived after the stock-out it is said to explain
- **THEN** its timing factor is 0.5

### Requirement: Guarded narrative

Gemini SHALL narrate the evidence graph with the A.3 schema citing node ids. The Number Guard SHALL reject any number not present in the cited node's facts, and the deterministic template SHALL be used as fallback.

#### Scenario: Guard

- **WHEN** a narrative contains a number that is not in its cited node's facts
- **THEN** the template narrative is stored and the violation is recorded
