# recommendation-execution

## ADDED Requirements

### Requirement: Idempotent executors after approval

The system SHALL execute approved recommendations through typed executors, run by a job enqueued in the same transaction as the approval. Execution SHALL happen exactly once per recommendation id and version, and there SHALL be no external side effect before approval.

#### Scenario: Supplier switch commits and emails a PO

- **WHEN** a GM approves the chicken thigh switch to Bramley Poultry & Fish
- **THEN** the default supplier changes and a draft PO at 7.19 per kg is created
- **AND** the PO is committed within the GM's PO limit, and one email to the supplier is recorded with its delivery status

#### Scenario: Replay is safe

- **WHEN** the execution job runs again for the same recommendation id and version
- **THEN** no second purchase order or email is created

### Requirement: PO commit within limits

A purchase order SHALL be committed only by a role whose PO approval limit covers its value, and emailed to the supplier on commit.

#### Scenario: Shift manager cannot commit

- **WHEN** a shift manager tries to commit a draft PO
- **THEN** the API returns 403
