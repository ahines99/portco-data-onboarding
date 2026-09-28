# Bounded task choices

The coordinator and participants select one scope before measurement. Fill source-specific
details privately. Choose a task small enough for the agreed cap, rather than promising that an
arbitrary extract supports all generated financial metrics.

| Card | Shared manual/assisted output contract | Completion check | Claim allowed |
| --- | --- | --- | --- |
| A: intake and profile | Declared schema/types, row counts, missingness, candidate keys, unit concerns and a findings report for specified tables | Reviewer checks frozen source counts and expected findings; all required items addressed or explicitly unsupported | Independent ingestion/profiling usability for that input |
| B: mapping review | Card A plus proposed canonical targets, units, joins, transformations, abstentions, evidence and reviewed decisions | Reviewer assesses all predefined target decisions, including missing/incorrect proposals; any approved content matches its packet hash | Independent mapping/review experience on that task |
| C: reviewed financial output | Card B plus the agreed dbt outputs, executable checks, independently referenced metric results and certified publication | Required financial controls pass; separate actual reviewer certifies; published hashes and audit chain verify | Scoped reviewed onboarding for those supported outputs |

Cards A and B do not prove financial certification. For C, enumerate required outputs and statuses
in advance. Unsupported metrics remain unsupported/`NEEDS_EVIDENCE`; they are not inferred from
unrelated data. A partial workflow cannot be relabeled complete after observing missing inputs.

For the assisted path, the CSV workflow is:

```text
uv run portco sources import-csv PRIVATE_MANIFEST --root PRIVATE_EXTRACT_ROOT
uv run portco run --connection csv:SOURCE_ID --stop-after schema_profiling
```

Card A stops after profiling. For B, start without `--stop-after` to reach the mapping-review gate.
For C, proceed through actual mapping decisions, sandbox results and certification as documented
in the [workflow walkthrough](../agent_walkthrough.md). Record the exact commands and run ID in
private evidence, and verify the gate after each resume. Ingestion itself is an operator action.

For the manual arm, use the operator's usual tools and require the same predefined outputs and
review standards. It need not reproduce this application's internal file layout. Record the
tools and effort; do not give it a pre-solved mapping or omit reconciliation to make it easier.
