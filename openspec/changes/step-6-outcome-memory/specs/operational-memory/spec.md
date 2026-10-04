# operational-memory

## ADDED Requirements

### Requirement: Memory entries

When an outcome is measured or a case closes, the system SHALL write one memory entry per case and kind. The entry holds subjects (entity references), cause code, a summary templated from records, actions, outcome, manager notes and dates, and is site-scoped.

#### Scenario: S7 history

- **WHEN** the demo is seeded
- **THEN** a closed case for the 19 Sep short delivery exists with an outcome memory entry (cause `supplier_short_delivery`, resolved by raising the par level, verdict improved)

### Requirement: Retrieval and citation

Candidates SHALL share a subject entity or cause code within 365 days at the same site. Each candidate is scored 0.5 × Jaccard of subjects + 0.3 × cosine (pgvector over Gemini embeddings) + 0.2 × 0.5^(age/60), and the top 3 with score ≥ 0.5 are returned. Statements about history SHALL cite only retrieved entries.

#### Scenario: S7 recalled in the S2 investigation

- **WHEN** the Friday 2026-10-02 drop is investigated
- **THEN** the 19 Sep case is returned with score ≥ 0.5 as the only similar case and cited by node id in the evidence
- **AND** it supports the `supplier_short_delivery` cause

### Requirement: Manager notes

Managers SHALL be able to attach notes to investigations, recommendations and cases; the notes become part of the case's memory.

#### Scenario: Note on the investigation

- **WHEN** the GM adds a note to the Friday investigation
- **THEN** the case's memory entries include the note and are re-embedded on next retrieval
