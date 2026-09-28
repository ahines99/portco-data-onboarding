# Inspectable evidence

The top-level artifacts come from actual deterministic fixture runs. Their reviewer decisions are
**automated synthetic test decisions**, not independent approvals by Alex. The separate
[live-study collection](live-study/README.md) contains six actual model sessions with no approvals.
Private workspace prefixes are replaced in shareable outputs. The raw local state
remains outside Git. The manifest hashes the normalized shared files; it is not a signed audit export.

Start with [success](success-report.md), [controlled failure](failure-report.md),
[reconciliation](reconciliation.json), [certification](certification.json), and
[recovery verification](recovery.json). [Manifest](manifest.json) records source revision, dirty-state
flag, dependency versions, fixture/lock hashes and file digests. The replay has its own source revision
and timestamp because it is a separate actual run.

Reproduce with `uv run python -m scripts.release_evidence` and
`uv run python -m scripts.record_demo`. Both allocate fresh temporary runtime state rather than
resetting an existing user's run. They make no model API calls. A source revision with documentation
or evidence changes pending is explicitly marked dirty; do not interpret it as a pristine release build.

## Automated qualification release

The [current qualification plan](../AUTOMATED-QUALIFICATION.md) follows the owner's automation-only,
free-only instruction. It adds separate-agent execution and new technical evidence; it does not
convert automated decisions into human consent or customer validation. Actual PostgreSQL acceptance
passed on `25c6937` in [CI](https://github.com/ahines99/portco-data-onboarding/actions/runs/36443092813).
Consult [release status](../RELEASE-STATUS.md) and the
[v0.2.0-rc.3 record](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.2.0-rc.3)
for integrated verification, checksummed artifacts and the exact release commit.

| Evidence | Observed scope | Boundary |
|---|---|---|
| [Operator attempt](agent-operator-qualification/README.md) | CLI operation and denied same-starter review on pinned baseline `03c4fb3` | Existing prepared environment and supported synthetic source; no independent installation or human timing study |
| [Separate reviewer completion](agent-reviewer-qualification/README.md), [verification](agent-reviewer-qualification/verification.json) | Six metrics published, 38 publication files verified, 46 audit events; explicit decisions and no waived failures | Automated, source-informed and not blinded; distinct from the nine-metric SaaS smoke |
| [V2 first result](agent-qualification-v2-first.json) | Six separately authored cases: 42/52 correct proposals, 42/43 positive targets, safety failure | Preserved first outcome; not external human evaluation |
| [V2 remediation](agent-qualification-v2-remediation.json) | Same accuracy, 48/52 proposals review-bound, safety passing, ten unresolved fields | Feedback-informed repair; ten wrong proposals remain wrong |
| [PostgreSQL connector](../POSTGRES-SOURCE.md), [actual CI](https://github.com/ahines99/portco-data-onboarding/actions/runs/36443092813) | 11 synthetic tables / 14,639 rows, nine metrics, 58 generated hashes, 59 published files, 45 audit events, zero waivers | Actual database extraction through publication with a scripted separate reviewer; no customer access, production backend or synchronization claim |

[Corpus provenance, freeze hash and methodology](../../evals/agent_qualification_v2/README.md) explain
what was frozen before inference and what changed afterward. The original 0/10 probe and v1 reports
remain separate historical experiments; none is overwritten or combined into an invented trend.
The historical v1 remediation had 7/33 proposals requiring review. Its [current regression](unfamiliar-benchmark-rc3.json) after the
entity-uncertainty repair has 17/33 review-bound proposals, while retaining safety, 32/33 correct
proposals, 32/32 target coverage and eight unresolved fields. The historical report is unchanged.

The [human operator pilot](operator-pilot/README.md) remains unexecuted. Automated qualification
reports can show reproducible execution and recorded review behavior, but not analyst savings,
customer adoption, independent human usability or live-production acceptance.
