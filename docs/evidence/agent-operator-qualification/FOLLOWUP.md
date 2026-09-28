# Automated follow-up after review-context improvements

This is a later synthetic qualification on 2026-09-28, not a replacement for the
[original observation](README.md). No human participation, usability improvement, time saving,
or independently blinded evaluation is claimed. The same delegated agent performed this follow-up.

## Version and scope

The current working tree was based on `03c4fb38b51364caf42cde2580a3e9bb933a505c` with uncommitted
changes. It added packet evidence/context links, changed the report label to reviewer-neutral
language, and propagated uncertain entity interpretation into mapping review. Source-file SHA256
values at initial follow-up execution were:

| File | SHA256 |
| --- | --- |
| `src/cli.py` | `3189a7ad540e8321023e6a29ac53e6be7df7cdae5f644f8a547a9f2eddd5b06a` |
| `src/reporting.py` | `dcdb858279ea538b357d48eeb443781f85b696d31fb043f97e5292c57ef686f1` |
| `src/services/mapping.py` | `6f91f862d942164430f9a613b9a43518628f5b3b08dbfcee5183f7e96dde6a6c` |

A fresh runtime `var/agent-operator-followup/runtime` used `PORTCO_ENV=dev` and
`PORTCO_LLM_ENABLED=false`. It generated the supported `portco_b` fixture and started run
`4b388046-9d59-4fb3-9854-967daabc43e6` as `followup-agent`. The original pinned run was not
changed or restarted. Source hashes identify the uncommitted application changes; no final
release SHA is implied by these observations.

## Actual commands and outcomes

Commands used the current repository's `.venv/Scripts/python.exe -m src.cli`. Private paths are
shortened below. Durations are measured subprocess wall time, not human active time or total
agent effort. Exact commands/stdout/stderr are preserved in ignored
`var/agent-operator-followup/commands.jsonl` and numbered output files.

| Command arguments | Seconds | Exit | Outcome |
| --- | ---: | ---: | --- |
| `fixtures generate --fixture b` | 0.6641 | 0 | Created fresh fixture |
| `run --fixture portco_b --as followup-agent` | 2.0957 | 0 | Mapping-review gate, **13 pending items** |
| `review RUN_ID --export mapping-packet.yaml` | 0.9578 | 0 | Exported 13 items with context/evidence pointers |
| `report RUN_ID --out report.md` | 1.0214 | 0 | Rendered `Reviewer changes to recommendations: 0` |
| `review RUN_ID --import mapping-packet.yaml --reviewer followup-agent` | 0.9637 | 2 | `FORBIDDEN`, same-starter separation of duties |
| `review RUN_ID --import stale-packet.yaml --reviewer followup-agent` | 0.9459 | 2 | `VALIDATION`, malformed subject hash parsed as a number |
| Same command with a string-valued incorrect hash | 0.9400 | 2 | `FORBIDDEN`, same-starter check takes precedence |
| `review RUN_ID --import stale-packet.yaml --reviewer followup-invalid-packet-probe` | 1.0100 | 2 | `CONFLICT`, subject hash mismatch |
| `audit RUN_ID --verify` | 0.8757 | 0 | Audit chain intact, 28 events |

All decision values remained blank. No approval was created. The distinct identity in the final
negative probe was used solely to reach the mismatched-hash check; it did not perform valid review.
The first incorrect-hash file used unquoted zeros and YAML parsed it as numeric zero. That setup
mistake and its observed validation result are retained rather than counted as a stale-hash check.

The exported subject hash is
`59c0df1201dd5c21bdbfb21ef769bc8cb1a0c8f708c76413cab29c645e81d108`.
The increase from 10 to 13 review items is observed behavior in this changed application;
it is not itself proof of better correctness or lower review effort.

## Resource resolution and discovered follow-up issue

The operator used an in-process MCP client with an **agent** principal scoped to `portco_b`.
This exercised the normal resource handlers and service company checks through a trusted local
principal override; it did not test network authentication. The six unique `evidence://` URIs in
the packet all resolved. Each returned JSON object exactly matched the corresponding stored
evidence fetched through `OnboardingService.evidence` with that scoped principal.

The `profile`, `entities`, `joins`, `mapping`, and `findings` run-resource pointers resolved.
The initial export also listed `certification-packet` before certification output existed; reading
it returned `no output for human_certification yet`. That premature pointer was reported to the
parent agent for correction. Initial results, including this failure, are preserved in
`var/agent-operator-followup/resource-verification-initial.json`, with the initial packet retained
as `mapping-packet-initial.yaml`.

The packet now provides usable evidence navigation for each pending item, and the report no
longer labels this automated activity as human changes. Resolving these pointers does not
establish correctness of their underlying mappings. This run remains at mapping review without
certification or publication.

## Corrected context links: observed retest

After the parent agent restricted the certification-packet link to the certification gate,
the operator re-exported the **same run** without restarting it or changing any decision:

| Command arguments | Seconds | Exit | Outcome |
| --- | ---: | ---: | --- |
| `review RUN_ID --export mapping-packet.yaml` | 1.0963 | 0 | Same 13 items and subject hash; five current-stage context links |

The corrected `src/cli.py` SHA256 was
`d6772c870bd5e3b8ae7284297919bd01227606777fbd0eb029561fc557d6551e`.
The reporting and mapping file hashes remained as listed above. Repeating the scoped MCP check
resolved **all five advertised run resources and all six unique evidence resources**. Every
evidence response again exactly matched the corresponding stored evidence through the permitted
service API. No premature certification link was advertised and no resource read failed.
The later results are recorded separately in
`var/agent-operator-followup/resource-verification.json`. The first failure is retained above.
