---
name: semantic-layer-generation
description: Use when explaining which metrics were generated into the semantic layer, why others were not (NEEDS_EVIDENCE vs reference-only), and what a reviewer should check before certifying a metric definition.
---

# Semantic layer generation

Metrics come from `ontology://pe/v1`. A metric is generated **only** when every field it requires
was mapped and approved. Anything else is listed with a reason in the bundle README and the
certification packet (`run://{run_id}/certification-packet`).

## Metric status

| Status | Meaning | What to say |
|---|---|---|
| `generated` | A MetricFlow simple or derived metric exists and reconciled in the sandbox | Cite the reconciliation check (`metric:billings`, `metric:arr`, ...) |
| `reference_only` | Cohort logic (NRR, GRR, ARR bridge, DSO, ARPA, headcount) computed by the reference service | It is exact but not exposed as a semantic metric in v1 |
| `not_generated` + `NEEDS_EVIDENCE` | A required field had no approved mapping | Name the missing fields. Never offer a proxy |

To see one metric's formula, grain and pitfalls, read `ontology://pe/v1/metrics/{metric}`.

## Definition discipline

- **Grain.** Every metric here is monthly. Time dimensions are day-grain with a month-end snapshot
  for recurring revenue.
- **Additivity.** Billings and revenue add up over time; ARR and MRR are point-in-time and must
  never be summed across months.
- **Currency.** Metrics are per currency unless an approved FX source exists (none in v1).
- **Derived metrics** (`gross_margin_pct`, `ebitda`) exist only when all their parts exist.
  Rejecting a parent at certification removes its dependents too.

## Certification checklist (what the human reviewer confirms)

1. The formula in the packet matches the company's definition, including gross vs net and credit notes.
2. The reconciliation check for the metric passed exactly. Money is compared at zero tolerance.
3. The time basis is right: invoice date, posting date, or subscription month end.
4. Known data issues in the packet's open findings (stale tables, orphans, duplicates) are acceptable.
5. The metric is not a proxy for something else, such as bookings standing in for revenue.

You may prepare this checklist for the reviewer, but `certify_run` accepts reviewer principals
only. After certification, `publish_run` needs the certification's approval id.
