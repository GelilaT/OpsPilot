# Proposal

## Why

Flow 2 produces investigations with ranked causes but no closed loop. Flow 3 turns evidence into approvable recommendations, executes them after sign-off, and tracks each incident end to end as an OperationsCase (SRS MVP Flow 3).

## What Changes

- Persistence:
  - `operations_case` (status derived from records, impact for ranking), `case_event` (timeline);
  - `recommendation` (+ notes, executed_at), `recommendation_transition`, `recommendation_execution` (+ error, at);
  - `ops_task` (+ due date, closing note), `email_delivery`.
- Recommendation state chart with 409 on illegal transitions, If-Match 412, approver role per type. Adjust allows only declared parameters, re-runs the impact formula and bumps the version. Supersede uses the same subject and type.
- Generators priced from site data:
  - supplier_switch: ≥5% cheaper and fill rate ≥95%; weekly usage × price difference.
  - par_level_change: order-up-to with safety stock; lost GP avoided − holding cost.
  - price_review: FR-MNU-06, two volume scenarios.
  - purchase_order: par gap.
  - waste_reduction, staffing_change, investigate_task: investigate_task is used for low-confidence causes.
- Executors keyed `rec_id:version`, run by the `action.execute` job that approval enqueues in the same transaction:
  - supplier_switch: change the default supplier, raise a draft PO, commit it within the approver's PO limit, email the supplier.
  - par_level_change: update the par level.
  - purchase_order: draft PO, committed via POST `/purchase-orders/{id}/approve`.
  - price_review and the others: Owner/GM tasks.
- Email through `email.send` with retries and recorded delivery status (FR-BRF-05).
- The agent opens the case, records every step, proposes, executes after approval, schedules the follow-up, and closes the case on rejection or expiry with the reason (writing memory).
- REST:
  - `/cases` (ranked), `/cases/{id}`, `/cases/{id}/timeline`;
  - `/actions` (queue by impact × confidence, filters), `/actions/{id}` (+ approve/reject/adjust/outcome);
  - `/purchase-orders` (+ approve), `/tasks` (+ close).
- 16:00 follow-ups: expire overdue proposals and nudge pending approvals.

## Capabilities

### New Capabilities

- `action-centre`: OperationsCase, recommendations, approvals, queue and timeline (FR-ACT-01..04, 08, 09, 11..13).
- `recommendation-execution`: idempotent executors, PO commit within limits, supplier email (FR-ACT-05/06, FR-PRC-07/08/10, FR-BRF-05).
- `nightly-pipeline`: the agent proposes recommendations after each investigation (ADDED requirement).

## Impact

- `api/migrations/0006_*`, `0007_*`.
- `api/app/domain/actions/*`, `domain/purchasing/orders.py`, `domain/notifications/*`.
- `api/app/api/v1/{actions,cases,purchase_orders,memory}.py`, `workers/nightly_tasks.py`, tests.

## Review note (SRS fidelity correction)

The first implementation of this change was reworked after review against SRS v2.1:

- Generators were hardcoded to chicken: 118 kg, +6 kg par, an £84 floor, a £55 price review.
- Case status was set ad hoc, and the timeline held only transitions.
- Execution ran synchronously in the request rather than through a job.
- The supplier-switch PO was committed without a PO limit check.
- Emails had no recorded delivery.
