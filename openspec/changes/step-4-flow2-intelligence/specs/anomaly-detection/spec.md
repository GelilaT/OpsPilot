# anomaly-detection

## ADDED Requirements

### Requirement: Detector registry with baselines, fingerprints and severity

The system SHALL run the v1 rules (AR-01..AR-09) and the v2 detectors nightly per site:

- v2: price_increase, stock_out, margin_decline, supplier_fill_rate, and the FR-MNU-05 menu checks.
- Baselines: same-weekday median and MAD; skip and log when there are fewer than 3 baseline points.
- Severity: from weekly money impact (AR-05/06 keep their v1 info severity).
- Fingerprints: one per detector + subject + episode; repeats extend the streak instead of duplicating.

#### Scenario: Friday dinner drop

- **WHEN** Friday 2026-10-02 dinner revenue falls 29% below the 4-week Friday median after the chicken stock-out
- **THEN** a critical `daypart_revenue` anomaly SHALL be recorded and the chicken thigh `stock_out` SHALL be detected at the time the dishes stopped selling

#### Scenario: Idempotent re-run

- **WHEN** the nightly pipeline is re-run for the same date
- **THEN** no new anomalies, investigations or cases are created

### Requirement: Auto-investigate and fold related anomalies

The system SHALL start an investigation automatically for new or escalated warning and critical anomalies; info anomalies go to the brief. Same-day related anomalies, and anomalies on entities the investigation implicated, SHALL be folded into the root anomaly's case.

#### Scenario: One incident, one case

- **WHEN** the Friday drop, the chicken stock-out, the chicken price increase and the Chicken Wrap margin decline are detected together
- **THEN** exactly one operations case is opened for the incident, with the others linked as related anomalies

### Requirement: Dismissal suppresses a fingerprint

An anomaly dismissed as expected SHALL suppress the same fingerprint for `detection.dismiss_suppress_days` (7).

#### Scenario: Dismissed price increase

- **WHEN** a GM dismisses an info price increase and the nightly pipeline runs again
- **THEN** the anomaly stays dismissed and no duplicate is created
