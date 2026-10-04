# Tasks

- [x] OpenSpec artifacts (proposal, design, specs, tasks)
- [x] Migration 0006 + ORM models; 0007: case_event, email_delivery, recommendation/execution/task columns
- [x] State chart, derived case status, case events, supersede, adjust with declared parameters
- [x] Generators priced from data (switch, par, price review, PO, tasks)
- [x] Executors keyed `rec_id:version`; draft PO → commit within limit → supplier email (`email.send`)
- [x] `action.execute` job enqueued with approval; failure path; follow-up date on the business clock
- [x] REST: `/cases` (+ detail, timeline), `/actions` (+ approve/reject/adjust/outcome), `/purchase-orders` (+ approve), `/tasks` (+ close)
- [x] 16:00 follow-ups (expire + nudge email)
- [x] Integration `test_step5_flow3.py`: queue and pricing; RBAC/412/409/adjust; switch → committed PO + email + idempotent replay + timeline; PO limit; cross-tenant 404

## SRS fidelity corrections (review of the first implementation)

- [x] Remove hardcoded chicken constants and floors from generators
- [x] Derive case status from records; timeline from case events
- [x] Execute through the job engine instead of inside the approval request
- [x] Enforce PO approval limits on commit; record email delivery
- [x] `nightly-pipeline` delta: ADDED, not MODIFIED (no base spec existed)
