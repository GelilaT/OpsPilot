# action-centre

## ADDED Requirements

### Requirement: Operations case, derived status and timeline

The system SHALL open one operations case per warning or critical incident. Its status (detected, investigating, awaiting_approval, executing, monitoring, closed) SHALL be derived from its investigation and recommendations. Every agent and human step SHALL be recorded with timestamp, actor and evidence link, exposed by GET `/api/v1/cases`, `/cases/{id}` and `/cases/{id}/timeline`.

#### Scenario: Case opens after investigation

- **WHEN** the nightly pipeline completes the Friday investigation
- **THEN** a case exists in `awaiting_approval`, ranked first on the dashboard by expected impact
- **AND** its timeline lists detected → investigated → proposed

### Requirement: Recommendation workflow

Each recommendation SHALL store its evidence reference, expected weekly impact with formula and inputs, risk and notes, confidence, required approver role, expiry, follow-up date and success metric:

- Illegal transitions SHALL return 409, and a stale If-Match SHALL return 412.
- An approver below the required role SHALL get 403.
- Adjust SHALL accept only declared parameters, recompute the impact and increment the version.
- A new recommendation for the same subject and type SHALL supersede a pending one.

#### Scenario: Owner adjusts a price review

- **WHEN** the Owner adjusts the Chicken Wrap price review from 9.95 to 10.50
- **THEN** the version increments and the expected weekly impact is recomputed from the same formula

#### Scenario: Wrong role

- **WHEN** a head chef approves a supplier switch
- **THEN** the API returns 403 with code `approval_limit`

### Requirement: Action queue API

The system SHALL expose GET `/api/v1/actions`, sorted by expected weekly impact × confidence and filterable by status, type and case.

#### Scenario: Queue ordering

- **WHEN** multiple recommendations are proposed
- **THEN** the list is ordered by descending impact × confidence
