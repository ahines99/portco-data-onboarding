# ADR-0008: dbt runs in a disposable sandbox, as a subprocess

- Status: accepted (amended from the roadmap: subprocess instead of in-process `dbtRunner`)
- Date: 2026-09-23

## Context
"Generated SQL runs in sandbox first." The roadmap proposed invoking dbt in-process through
`dbtRunner`. In-process dbt prints to stdout, which would corrupt the stdio MCP transport. It also
holds global state and cannot be killed on timeout.

## Decision
The sandbox copies the source into a private build directory, attaches it read-only in the dbt
profile (`attach: read_only: true`), and runs `dbt build` as a subprocess with a timeout and a
minimal environment (no secrets are inherited). When the build and reconciliation finish, the
directory is renamed to its key, `var/sandbox/<run>/<bundle>-<fingerprint>`, so an attempt that was
abandoned on timeout can never write into a later attempt's directory. A path check refuses any target outside the sandbox root. Results are cached per
bundle manifest and source fingerprint, so resuming and rerunning are cheap. Reconciliation
recomputes metrics in Python from the sandbox copy and compares them with the marts exactly.

## Alternatives considered
- In-process `dbtRunner`: rejected for the reasons above.
- A container per build: deferred to production. It gives stronger isolation (network, filesystem),
  but needs a container runtime on every developer machine and in CI.
- Running generated SQL directly without dbt: rejected. The deliverable is a dbt project, so it must
  be tested as one.

## Consequences
A build costs a process start and a file copy of the source, which is fine at fixture scale. Real
warehouses need a different sandbox strategy (a zero-copy clone, or a scratch schema with read-only
grants); that is v0.2 work behind the same step.

## Evaluation
G08 and G09 (exact match with ground truth), G20 and G28 (failures stop the run),
`test_dbt_cannot_target_outside_the_sandbox`, and the `source_unchanged` check.
