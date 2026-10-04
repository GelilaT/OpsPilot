# Design — Step 6 Outcome and memory

## Outcome evaluation

- Execution business date = follow_up_at − `actions.follow_up_days`. On the simulator clock, wall-clock execution time is not the business date.
- Pre window: 14 days up to execution. Post window: the day after execution up to the follow-up date.

| Success metric | Series |
|---|---|
| cost_per_base_unit | daily cost per base unit paid on that day's receipts (days without a delivery carry no observation) |
| stock_out_count | stock-outs per day (intraday reconstruction) |
| item_gp_pct | snapshot GP |
| labour_pct | labour % of revenue |
| usage_variance | COGS % (proxy until stock counts are in the MVP) |
| task_closed | task status |

- counterfactual = last pre value + Theil–Sen slope × (h + 1) / 2 (mean of the projected post days); effect = mean(post) − counterfactual.
- improved: same sign as expected and |effect| ≥ ½|expected|. worsened: opposite sign and |effect| > σ(pre). Otherwise no_change.
- Expected effect per metric: switch −price difference; par −stock-outs/week ÷ 7; price review +GP points.

S3/S7 demo: the switch is executed on 2 Oct and Bramley's first delivery arrives on 3 Oct. A 70 kg Ashworth order placed before the switch also arrives that day. The post-window mean cost per kg is 7.30 against a counterfactual of 7.90 (−7.6%, expected −9%): improved. Appendix B states −8.7%.

## Memory

- Summary text is templated from records ("19 Sep 2026: Supplier short delivery → ingredient stock-out. Ashworth Meats Ltd delivered 14 kg of 20 kg … Resolved on 21 Sep by raising … par level from 15 kg to 18 kg.").
- `subject_keys` holds `type:id` strings with a GIN index; `embedding` is vector(768) with an ivfflat cosine index (lists = 10 at demo volume).
- The query subjects are the investigation's causal entities (ingredient and supplier), so the score compares like with like. For S7 → S2 that gives Jaccard 1.0, cosine ~0.16 (hashed fake) and recency 0.87 (13 days): score 0.72.
- A recall adds (0.35, score) evidence to the cause it shares; that is how the S2 confidence reaches 0.86.
- Notes rewrite the entry's notes and clear its embedding, which is re-embedded at the next retrieval (batches of 10).

## Dispatcher

`due_jobs(now, sites)` is pure (unit-tested). `dispatch()` inserts `schedule_run (site, job, local_date)` ON CONFLICT DO NOTHING and enqueues only when the insert wins. The job key is `job:site:business_date`, on the site lock so the jobs run in order. Cloud Scheduler calls it with OIDC; X-Cron-Secret is the fallback.

## Simulator corrections found here

- The world orders from `site_ingredient.default_supplier_product_id`, so a switch changes deliveries.
- A second PO from the same supplier on the same day is its own delivery (GRN id and invoice number suffixed).
- POs due today whose invoice was posted first are still delivered (goods receipt linked to the invoice).
