# margin-intelligence

## ADDED Requirements

### Requirement: Daily item cost and GP snapshots

The system SHALL compute each menu item's cost at a business date as the sum of recipe base quantities times the ingredient's weighted average cost at the end of that day. It SHALL persist price ex VAT, GP %, contribution margin, units sold, total contribution and a per-ingredient breakdown in `item_cost_snapshot` nightly, and SHALL backfill the seeded history.

#### Scenario: Chicken Wrap GP after the chicken price increase

- **WHEN** INV-4471 is posted (chicken thigh 6.70 → 7.90 per kg) and the nightly pipeline runs for 2026-10-02
- **THEN** the Chicken Wrap snapshot cost SHALL be 2.83 and GP 64.3%, against 2.53 and 68.1% on 2026-09-04 (the start of the 28-day window)
- **AND** the item attribution SHALL show chicken thigh from Ashworth Meats explaining 80% of the increase

### Requirement: Repricing suggestion

The system SHALL compute the gross price that restores the target GP %, rounded up to the site's price endings, with the weekly GP impact at current volume and at −5% volume, and SHALL never change prices automatically.

#### Scenario: Chicken Wrap what-if

- **WHEN** a GM requests the what-if for the Chicken Wrap with target GP 65%
- **THEN** the suggestion SHALL be 9.50 → 9.95 with GP 65.9% and a positive impact at both volumes

### Requirement: Menu cost timeline API

The system SHALL expose GET `/api/v1/menu/items/{id}/cost-timeline` and `/attribution` returning dated snapshots and the ingredient and supplier drivers of a cost change.

#### Scenario: Timeline query

- **WHEN** a GM requests the cost timeline for a menu item over a date range
- **THEN** the API returns ordered snapshots including GP %, units and the cost breakdown by ingredient name
