# Agent-operated CLI qualification

An agent operated the public CLI on 2026-09-28 against application baseline `03c4fb3`.
This is automated synthetic qualification, not a human pilot, customer acceptance, independently
validated usability study, or measurement of time saved. No human operator or reviewer participated
in this bounded attempt. A separate delegated automated reviewer may continue the run; that
continuation must retain its own provenance.

## Task and boundaries

The operator was a delegated Codex agent with principal `qualification-agent`. Its assigned task
was to use the new pilot-kit setup/task instructions on the unrelated `portco_b` synthetic fixture,
reach mapping review, inspect the exported packet, safely attempt a prohibited same-starter review,
and hand off actual findings. The operator did not read mapper implementation or benchmark labels,
change production code, submit valid review decisions, or use `--default approve`.

The parent agent supplied an existing isolated baseline installation. Therefore these observations
do not test installation by a new user. Environment settings were `PORTCO_ENV=dev`,
`PORTCO_LLM_ENABLED=false`, and a fresh isolated `PORTCO_VAR_ROOT`. The optional application LLM judge
was disabled; the operator itself was an AI agent. Local identity arguments are trusted operator
inputs, not proof of a remotely authenticated principal.

## Observed execution

Run: `ebdbc80e-859c-4b3e-836b-afc3b3b4159e`.

Commands below were invoked as `python -m src.cli` from the isolated baseline. Paths have been
shortened to omit the workstation account and root directory. Durations are subprocess wall-clock
seconds, including process startup. They exclude agent reasoning/tool orchestration and are not
human active-time measurements. No manual baseline was observed.

| Command arguments | Seconds | Exit | Observed result |
| --- | ---: | ---: | --- |
| `fixtures generate --fixture b` | 0.7178 | 0 | Generated isolated `portco_b.duckdb` |
| `run --fixture portco_b --as qualification-agent` | 2.0275 | 0 | Paused at mapping review with 10 pending items |
| `review RUN_ID --export mapping-packet.yaml` | 0.9398 | 0 | Wrote the 10-item packet |
| `report RUN_ID --out report.md` | 0.9049 | 0 | Wrote findings, proposals and timeline |
| `review --help` | 0.7682 | 0 | Confirmed import and reviewer identity options |
| `review RUN_ID --import mapping-packet.yaml --reviewer qualification-agent` | 0.9247 | 2 | Rejected same-starter review with `FORBIDDEN` |
| `audit RUN_ID --verify` | 0.9672 | 0 | Audit chain intact, 21 events |

The intentional forbidden request submitted the unchanged packet, with decisions still blank.
The explicit error was: `the principal that started a run cannot approve it (separation of duties)`.
This proves that observed same-principal attempt was refused. It does not independently test the
MCP agent-role permission boundary or prove that a complete decision packet would otherwise pass.

The mapping subject hash exported before review was
`0fab9f6df411995005b17e82e645ddb2d8c3175aae9f01526b503c0a664371d6`.

## Actual review handoff

The report identified one schema, seven visible tables, a rejected source write probe, two
soft-deleted rows, two PII-classified columns, and four proposed joins. The packet requires these
decisions; the operator has not approved their correctness:

| Item | Proposed interpretation | Review concern |
| --- | --- | --- |
| `sap.BSEG.DMBTR_S` | General-ledger debit amount | Metric-bearing monetary value |
| `sap.BSEG.DMBTR_H` | General-ledger credit amount | Metric-bearing monetary value |
| `sap.PA0001.ENAME` | Employee full name, hashed | PII handling |
| `sap.PA0001.GBDAT` | Date of birth, excluded | PII handling |
| `sap.VBRK.KUNAG` | Invoice customer ID | Medium confidence and inferred join |
| `sap.VBRK.NETWR` | Invoice total amount | Medium confidence and monetary interpretation |
| `sap.VBRK.FKART` | Invoice status | Low confidence; billing-type semantics may differ from status |
| `sap.VBRP.NETWR` | Invoice-line amount | Low confidence and amount interpretation |
| `sap.KNA1.LOEVM` filter | Exclude flagged rows | Proposed exclusion affects two rows |
| `sap.VBRK.KUNAG -> sap.KNA1.KUNNR` | Many-to-one customer join | Structural inference; reported 100% containment, no orphans |

The report left 11 metrics as `needs_evidence`, including ARR and MRR. No financial generation,
reconciliation, certification, or publication was performed in this operator attempt. The separate
reviewer must examine source evidence rather than treat candidate confidence as approval.

## Friction and limitations observed

- The run's next-command hint led directly to the packet export; no corrective command or code fix
  was needed to reach the gate.
- The packet includes candidates, alternatives, confidence, transforms, and review reasons but not
  source examples or full supporting evidence. The reviewer needs the accompanying report/profile
  and source documentation to adjudicate ambiguous names.
- The generated report labels a counter `Human changes to recommendations` even though this
  attempt used an agent. Its value was zero; the label does not establish human involvement.
- The pilot-kit prose describes human participants. This exercise adapted its technical setup to
  the user's later automation-only instruction, without claiming to satisfy human participation.
- The source is an existing supported fixture. Successful navigation is not evidence of unfamiliar
  schema generalization, customer adoption, or financial accuracy.
- This delegated agent inherited project conversation context. It is a separately operated attempt,
  not a blinded or externally independent study.

Private raw command records and outputs are under ignored `var/agent-operator-qualification/`.
The runtime root is `var/agent-operator-qualification/runtime`; the baseline source is under
`var/roadmap-execution/baseline-03c4fb3/source`. No raw source rows are reproduced here.
