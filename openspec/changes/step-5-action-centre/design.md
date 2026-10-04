# Design — Step 5 Action Centre

## Case lifecycle (FR-ACT-11)

One `operations_case` per root anomaly (unique `anomaly_id`). Its status is a projection recomputed by `refresh_case` on every change:

| Status | Condition |
|---|---|
| `detected` | no investigation yet |
| `investigating` | investigation running or no recommendations |
| `awaiting_approval` | any recommendation proposed |
| `executing` | any approved or executing |
| `monitoring` | any completed or follow_up (awaiting outcome) |
| `closed` | every recommendation terminal (rejected, expired, superseded, failed, outcome_measured); the anomaly closes too |

`case_event` records every agent and human step with actor, summary and an evidence ref: detected, investigated, proposed, approved, adjusted, executing, executed, follow_up_scheduled, outcome_measured, memory_written, note, closed. The timeline API returns these rows.

## Recommendation flow (FR-ACT-03)

```
draft → proposed → approved → executing → completed → follow_up → outcome_measured
           ↓ rejected / expired / superseded             ↘ failed
```

- Approval checks the role (APPROVER per type), If-Match and expiry, then transitions to `approved` and enqueues `action.execute` (key `action.execute:{id}:{version}`) in the same transaction.
- The worker transitions to `executing`, runs the executor in a savepoint (failure → `failed` with the error), then `completed` → `follow_up` with `follow_up_at = business date + actions.follow_up_days`.
- Adjust is allowed only in `proposed` and only for `impact_inputs.adjustable`. It re-runs `impact.recompute`, bumps the version and records an event.

## Generators

| Type | Formula (impact_inputs) | Approver | Success metric |
|---|---|---|---|
| supplier_switch | weekly usage (28-day theoretical) × price difference; FR-PRC-10 candidate | GM | cost per base unit |
| par_level_change | par = mean daily need × review period + z·σ·√(L+R) (stock-out day un-censored); impact = lost GP × stock-outs/week − holding | Head Chef | stock-out count |
| price_review | FR-MNU-06 suggestion; only when GP is below target | Owner | item GP % |
| purchase_order | par gap at the default supplier, when no switch is proposed | Head Chef (within PO limit) | stock-out count |
| waste_reduction / staffing_change / investigate_task | anomaly weekly impact / n/a | Head Chef / GM / GM | variance / labour % / task closed |

Confidence is the motivating cause's confidence. A price review without a cause gets 0.5: the GP gap is measured exactly, the demand response is uncertain.

## Executors (FR-ACT-05, FR-PRC-08)

The execution key is `{recommendation_id}:{version}` (unique). A replay returns the recorded execution.

- supplier_switch: change `site_ingredient.default_supplier_product_id`, then create a draft PO for the par gap at the new supplier. If the approver's `approval.po_limits` covers it, commit it (approved_by = approver) and queue the supplier email. Otherwise the PO waits in `pending_approval`.
- `commit_po` checks the limit and emails on commit through `queue_email` → `email.send` (MailPort, retries, `email_delivery` status).
- The simulator's world orders from the site's chosen supplier, so a switch changes what arrives.

## Exit

The GM approves the S3 switch. The worker executes it and PO-xxxx goes to Bramley (7.19/kg), committed and emailed. The `email_delivery` is `logged` (console adapter) or `accepted` (SendGrid). Replaying the job creates no second PO or email.
