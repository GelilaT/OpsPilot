# outcome-measurement

## ADDED Requirements

### Requirement: Counterfactual outcome and verdict

For every recommendation in follow-up whose date has passed, the system SHALL measure the success metric. The effect is the post-period mean minus the pre-period trend projected forward. The verdict is improved when the effect is in the expected direction and at least 50% of the expected impact, worsened when it is opposite beyond one standard deviation, otherwise no_change. The recommendation then moves to `outcome_measured`.

#### Scenario: Supplier switch seven days later

- **WHEN** the chicken thigh switch to Bramley is approved on 2026-10-02 and the simulator advances to 2026-10-09
- **THEN** the 06:00 evaluation records cost per kg below the 7.90 counterfactual by at least half the expected 0.71 and the verdict `improved`
- **AND** the case timeline shows `outcome_measured` and `memory_written`

### Requirement: Outcome API

The system SHALL expose GET `/api/v1/actions/{id}/outcome` with metric, windows, counterfactual, actual, effect (absolute and %), expected effect, sigma and verdict.

#### Scenario: Not yet measured

- **WHEN** the outcome of a recommendation still in follow-up is requested
- **THEN** the API returns 404 with code `outcome_not_measured`
