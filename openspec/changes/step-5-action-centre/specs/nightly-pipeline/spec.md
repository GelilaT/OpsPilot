# nightly-pipeline

## ADDED Requirements

### Requirement: Agent proposes actions after investigation

After each auto-investigation, the nightly pipeline SHALL open (or reuse) the operations case and propose the priced recommendations, superseding pending ones for the same subject and type.

#### Scenario: Proposals after the Friday investigation

- **WHEN** the nightly pipeline investigates the Friday 2026-10-02 drop
- **THEN** the case is `awaiting_approval` with a supplier switch, a par level change and a Chicken Wrap price review proposed
