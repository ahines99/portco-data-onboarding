# ADR-0008: dbt runs in a disposable sandbox, as a subprocess

- Status: accepted (amended from the roadmap: subprocess instead of in-process `dbtRunner`)
- Date: 2026-09-23

## Context
"Generated SQL runs in sandbox first." The roadmap proposed invoking dbt in-process through
`dbtRunner`. In-process dbt prints to stdout, which would corrupt the stdio MCP transport. It also
holds global state and cannot be killed on timeout.

## Decision
The sandbox copies the source to `var/sandbox/<run>/<bundle>-<fingerprint>/source.duckdb`, attaches
it read-only in the dbt profile (`attach: read_only: true`), and runs `dbt build` as a subprocess
with a timeout. A path check refuses any target outside the sandbox root. Results are cached per
bundle manifest and source fingerprint, so resuming and rerunning are cheap. Reconciliation
recomputes metrics in Python from the sandbox copy and compares them with the marts exactly.

## Evaluation
G08 and G09 (exact match with ground truth), G20 and G28 (failures stop the run),
`test_dbt_cannot_target_outside_the_sandbox`, and the `source_unchanged` check.
