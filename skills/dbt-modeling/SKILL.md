---
name: dbt-modeling
description: Use when inspecting, explaining or troubleshooting the dbt project generated from a reviewed mapping — staging/intermediate/mart layering, generated tests, sandbox results, and deciding whether a failure is a data problem or a mapping problem.
---

# dbt modeling (generated projects)

The dbt project is **generated** from a human-reviewed mapping and is byte-identical for the same
inputs. You never edit generated SQL by hand. If something is wrong, the fix is a mapping
decision followed by a rerun, and the new bundle is re-certified.

## Layering

| Layer | Models | Responsibility |
|---|---|---|
| staging | `stg_<schema>__<table>` | Rename to canonical fields, cast types, apply reviewed transforms, hash or drop PII, flag filtered rows with `_excluded` (rows are never deleted) |
| intermediate | `int_<schema>__<table>` | Scope rows: excluded when their own filter matches, or when the parent row they reference in *another* entity is excluded |
| marts | `dim_*`, `fct_*`, `fct_mrr_monthly` | One model per canonical entity from its system-of-record table, enriched from secondary tables of the same entity and lookups (e.g. account type on GL lines) |
| semantic | `semantic_models.yml`, `metrics/*.yml` | MetricFlow definitions for metrics whose inputs were approved |

Browse any generated file through `run://{run_id}/artifacts/{path}` (for example
`run://{run_id}/artifacts/models/marts/fct_invoice.sql`).

## Generated tests

- `unique` + `not_null` on primary keys (composite keys use `portco_unique_combination`).
- `not_null` on required fields that were 100% populated at profiling time (the observed contract).
- `relationships` on approved joins, at `warn` severity when the reviewed orphan rate is above zero.
- `accepted_values` on low-cardinality categories, and `non_negative` on money and quantity columns.

## Reading a sandbox result

Read `run://{run_id}/test-report` (the `run_sandbox_tests` tool returns a summary).

1. `dbt_exit_code` 0 and all reconciliation checks passing: the result is ready for certification.
2. A failing **data test** (for example `non_negative`) usually means the data is bad: negative
   quantities, credit lines booked as positive. Downstream models are skipped, so bad rows never
   reach marts.
3. A failing **reconciliation** (`metric:*`, `consistency:*`) means generated SQL and the Python
   reference disagree. That is almost always a **mapping** problem: a wrong transform, the wrong
   system of record, or a missing filter. Explain which mapping item is implicated.
4. A reviewer may waive failing checks at the `test_failures` gate. Waivers are audited and appear
   in the certification packet.

## Never

- Never edit generated files or suggest hand patches. Change the mapping, then run `resume_run`,
  or have a reviewer rerun from the mapping step.
- Never point dbt at anything but the sandbox. The generated `profiles.yml` only reads paths from
  sandbox environment variables and attaches the source read-only.
