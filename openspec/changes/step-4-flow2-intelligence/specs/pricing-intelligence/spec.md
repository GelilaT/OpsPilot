# pricing-intelligence

## ADDED Requirements

### Requirement: Supplier ranking

For an ingredient offered by two or more suppliers the system SHALL rank suppliers by latest normalised price, then fill rate, then lead time. Fill rate is received ÷ ordered over 90 days for PO lines due in the window, weighted by ordered value. When the goods receipt is absent, the posted invoice quantity stands in.

#### Scenario: Chicken thigh comparison

- **WHEN** a GM compares suppliers for chicken thigh after INV-4471
- **THEN** Bramley Poultry & Fish SHALL rank first at 7.19 per kg with a fill rate of at least 95%
- **AND** it SHALL be the switch candidate (at least 5% cheaper than the default Ashworth Meats)

### Requirement: Cost increase attribution

For a period against the prior period of equal length, the system SHALL attribute delta cost per ingredient as (current price − previous price) × current usage, aggregated by supplier, with money and % shares that sum to the total.

#### Scenario: Attribution totals reconcile

- **WHEN** attribution is requested for a period
- **THEN** the ingredient deltas sum to the reported total and the suppliers list the same total
