# Metric status examples

**Fixture A (SaaS).** Generated: `billings`, `mrr`, `arr`, `active_customers`, `revenue_recognized`,
`cogs`, `opex`, `gross_margin_pct`, `ebitda`. Reference-only: `nrr`, `grr`, `new_arr`,
`expansion_arr`, `contraction_arr`, `churned_arr`, `dso`, `arpa`, `headcount`. If a reviewer
rejects `cogs` at certification, `gross_margin_pct` and `ebitda` are excluded from publication too.

**Fixture B (industrial distributor).** Subscriptions do not exist, so `mrr`, `arr`,
`active_customers`, the ARR bridge, `nrr`, `grr` and `arpa` are `NEEDS_EVIDENCE`. The correct answer
is "not derivable from this source", not an estimate built from billings.
