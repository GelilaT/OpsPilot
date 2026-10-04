# nightly-pipeline

## ADDED Requirements

### Requirement: Nightly site pipeline

For a business date the system SHALL run, per site and idempotently:

1. Theoretical consumption from sales × the recipe active that day.
2. Item cost snapshots.
3. Detectors.
4. Auto-investigation with incident folding.

`simulator.next_day` SHALL enqueue the pipeline for the simulated date on the site lock.

#### Scenario: Simulated Friday

- **WHEN** the simulator advances Copper Pot to 2026-10-02
- **THEN** the pipeline for 2026-10-02 runs after the day's sales are ingested and produces the Friday case
