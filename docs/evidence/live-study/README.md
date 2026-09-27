# Six real model sessions

Collected 2026-09-27 against source `43920a34ce868b7ead5ebd2e47fdd80eb53be23d` using
Claude Code 2.1.280, model `claude-sonnet-5`, medium effort and a 24-turn limit. Authentication used
the owner's existing Claude subscription. No optional paid application judge was enabled.

Each session had fresh conversation and database state, the same fixtures, agent-only identity,
MCP capabilities and prompt. User settings, hooks, memory and unrelated MCP servers were excluded.
The condition order alternated: profile without/with, mapping with/without, failure without/with.
The five project Skills were discoverable only in the `with` condition; the `without` sessions had
no discoverable Skills. The [CLI](https://code.claude.com/docs/en/cli-reference) and
[Skill documentation](https://code.claude.com/docs/en/skills) describe these controls.

| Session | Seconds | Pending items | Skill bodies invoked | Response |
|---|---:|---:|---|---|
| Profile without | 24.34 | 22 | None | [Response](profile-without.final.md) / [full transcript](profile-without.txt) |
| Profile with | 28.55 | 22 | None | [Response](profile-with.final.md) / [full transcript](profile-with.txt) |
| Mapping with | 44.48 | 9 | canonical-pe-ontology | [Response](mapping-with.final.md) / [full transcript](mapping-with.txt) |
| Mapping without | 28.44 | 9 | None | [Response](mapping-without.final.md) / [full transcript](mapping-without.txt) |
| Failure without | 23.65 | 22 | None | [Response](failure-without.final.md) / [full transcript](failure-without.txt) |
| Failure with | 24.43 | 22 | None | [Response](failure-with.final.md) / [full transcript](failure-with.txt) |

All sessions completed without denied tool permissions or tool-result errors. All six persisted runs
were verified to remain `needs_review` at `mapping_review`; none called approval, certification or
publication. The malformed fixture sessions did not reach sandbox execution, so these model sessions
do not demonstrate that the model discovered the negative amount/quantity test failures.

The five Skill names in `comparison.json` mean **available to the model**, not that all five bodies
were read. Only one session invoked a Skill. This is a test of discoverable Skills under the fixed
prompts, not a forced-content experiment. The sample is small and unblinded; no general improvement
or timing advantage is claimed.

## Assistant review

The implementation assistant inspected the six responses and tool histories and prepared
[line-anchored annotation candidates](assistant-review.json). They include an incorrect metric count,
an incorrect join count and a promise by an agent to submit reviewer decisions. The mapping-with
response read more resources and distinguished billings from recognized revenue, but it also made
overconfident semantic claims and offered an action outside its role. More words and more tool reads
are not themselves evidence of better performance.

These candidates are not an exhaustive or independently validated error count. They are deliberately
separate from the human scoring manifest. `comparison.json` still has blank reviewer metadata and
`violations: null`; running the original scorer must reject it until a human reviews it. Do not put an
AI reviewer in that manifest and then call the resulting report human-reviewed.

## Provenance

[collection.json](collection.json) records prompts, tool names, Skill invocation, source commit,
run IDs, elapsed times and transcript hashes. The full normalized transcripts preserve the actual
assistant messages and tool inputs/results; only private filesystem prefixes were replaced.
Original stream JSON remains local. The public transcripts include model mistakes verbatim and
must be read as observations, not endorsed instructions.

The collection scripts and raw runtime state remain local under ignored `var/`; the release archive
contains the shareable transcripts and review material. No failed study sessions were discarded or
replaced. The earlier environment discovery did not run a model prompt.
