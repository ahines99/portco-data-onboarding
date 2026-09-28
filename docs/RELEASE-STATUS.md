# Portfolio release status

Updated 2026-09-27. The owner approved the hiring-focused, MIT-licensed public release at
[ahines99/portco-data-onboarding](https://github.com/ahines99/portco-data-onboarding).
The [public project page](https://ahines99.github.io/portco-data-onboarding/) is a static presentation
and actual scripted-output replay; it has no live backend or model API calls. Supplemental evidence
now includes [six actual model sessions](evidence/live-study/README.md), a synthetic-voice video and
an [owner-approved acceptance packet](ASSISTED-ACCEPTANCE.md). The v0.1.0 source tag remains immutable; v0.1.1 addresses the subsequent final-audit findings.

Engineering delivery is a **finalized portfolio release**, explicitly approved by Alex.
The delegated workflow and approved annotation report are complete. See [final acceptance](FINAL-ACCEPTANCE.md).
Independent usability and general Skill efficacy remain unclaimed optional validation, not release blockers.
The tagged GitHub release links its source commit, final CI run and distribution checksums; use that
record for the exact shipped code, rather than treating an earlier test count as a permanent guarantee.

## Final audit patch

The final three-agent review identified and reproduced review-packet binding, invoice consistency,
and annotation-provenance defects plus contradictory scope wording. Version 0.1.1 fixes these
with regression tests and adds an enforced fixable HIGH/CRITICAL image vulnerability gate.
See [audit closeout](FINAL-AUDIT-CLOSEOUT.md) and the exact tagged CI run linked from the
[release](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.1.1).
The verification below is historical v0.1.0 evidence; it is not a fresh v0.1.1 measurement.

## Completed verification

The first hosted run [36356573053](https://github.com/ahines99/portco-data-onboarding/actions/runs/36356573053)
passed all nine jobs on `b61d559`: lint/types, tests, security, PostgreSQL 16, eval, demo, Linux and
Windows minimal wheel/sdist installs, and actual container smoke. The subsequent run
[36357412472](https://github.com/ahines99/portco-data-onboarding/actions/runs/36357412472) adds application
dependency scanning and a machine-readable actual-image scan. The release's final run also tests the
later container hardening and PostgreSQL backup/restore additions.

| Evidence | Observed result |
|---|---|
| Windows full non-Postgres suite | 459 passed, 4 deselected; 243.11 seconds |
| First hosted non-Postgres suites | 355 general tests + 104 security tests passed |
| First hosted PostgreSQL 16 suite | 4 passed, including certified publication, concurrency and recovery |
| First hosted eval | 37/37 cases, gate PASS; 71.1 seconds |
| Reference calculator coverage | 100% statement/branch coverage in the CI coverage gate; not whole-project coverage |
| Minimal package | sdist-to-wheel build, base-only install, three demo paths and installed stdio MCP passed on Windows and Linux |
| Container | Migration 0003, auth refusal, separate synthetic roles, nine-metric publication, exact file hashes, audit and full stack recreation passed |
| Populated SQLite upgrade/restore | Three completed runs verified; 0002→0003 migration and same-path backup restore passed; [report](evidence/recovery.json) |
| Performance sample | Three actual cold/reused synthetic runs; raw timings and hardware in [benchmark](evidence/benchmark.json); no human waiting or scale claim |
| Browser presentation | Desktop 1440px and mobile 390px: no horizontal overflow or JS errors; replay play/pause/seek works; screenshots in `assets/` |
| Secret review | Gitleaks 8.30.1: existing history and staged changes reported no leaks |
| Application dependency review | Vulnerable sqlparse updated through compatible dbt-core; pip-audit reports no known application dependency vulnerabilities |
| Container dependency review | Actual image scanned; unused inherited pip removed; unfixed Debian findings retained and triaged in [security review](security-review.md) |

Evidence generation at commit `a424f88` began from a clean tree. Its [manifest](evidence/manifest.json)
records source, fixture/lock hashes and shared file hashes. Later documentation and test-tooling changes
do not turn those fixture outputs into a new run. The replay is a separate actual recording with its
own provenance. Private workspace paths are normalized; the shareable files are not signed audit exports.

## Roadmap disposition

| Task | Status and remaining boundary |
|---|---|
| PF-01 Scope/commits | Implemented; initial GitHub commit preserved and local history published |
| PF-02 Identity/license | Implemented; MIT, Alex Hines, repository/package links, contribution/security guidance |
| PF-03 Safe tooling | Implemented; Docker context exclusion and unique disposable PostgreSQL databases with explicit opt-in |
| PF-04 Containers | Implemented; named state volumes, verified recreation, dump/restore smoke, capability restrictions |
| PF-05 Hosted CI | Implemented; actual hosted runs, minimal permissions, required checks, no force-push/deletion on main; owner administration remains allowed |
| PF-06 First-run packaging | Implemented and automatically verified on Linux/Windows; independent human usability is PF-17 |
| PF-07 Operations | Implemented; populated migration/restore rehearsal and runbook; production operations outside scope |
| PF-08 Docs/claims | Updated; historical audit kept as a baseline, current claims linked to evidence |
| PF-09 Evidence | Implemented; success/failure reports, metrics, certification, lineage, samples, checksums and recovery proof |
| PF-10 Real agent session | Complete; original sessions retained, then one run certified/published under explicit owner delegation with new-run checks |
| PF-11 Skill study | Complete; six real transcripts and owner-approved annotation scores (3 without / 3 with); no efficacy claim |
| PF-12 Optional judge | Paid/live comparison deferred as agreed; unknown rates now remain unknown through reports instead of becoming $0 |
| PF-13 MetricFlow | Bounded investigation completed; CLI validation failed; [full runtime support explicitly deferred](metricflow-investigation.md) |
| PF-14 Generalization/performance | Small probe and three-run timing sample completed; broader representative/external study remains a depth item |
| PF-15 Case study | Complete; technical case study and personal wording approved by Alex |
| PF-16 Visuals/recording | Static site, replay, screenshots and captioned 3:51 synthetic-voice video delivered; personal narration optional |
| PF-17 Independent usability | Automated fresh-clone check completed; independent person's feedback remains external validation |
| PF-18 Security review | Performed; application fixes made, image findings disclosed; image remains unsuitable for untrusted production use |
| PF-19 Publication | Public repository and Pages site delivered; v0.1.0 promoted to final portfolio release with immutable tag, wheel and checksums |
| PF-20 Maintenance | Monthly/pre-release dependency review and verification runbook documented; no automatic paid tasks |

## Results that did not pass

The unfamiliar-schema probe returned **0/10 target matches with zero proposals**. Its zero
wrong-without-review count therefore does not mean successful mapping. No review or publication
was performed. [All labels/outcomes](evidence/heldout-probe.json) are retained; the mapper was not
tuned to turn this probe green. Recognized fixture vocabulary is a substantial scope limitation.

MetricFlow 0.15.0 configuration validation failed with a bytes/string parsing error in an isolated
environment. Only the local monthly semantic executor is currently supported. The judge has no
live benefit evidence and stays disabled. The six-session Skill collection found only one explicit
Skill invocation; the transcripts retain model errors and do not establish efficacy. The container
scanner reports upstream OS vulnerabilities without fixes; the release is not a production image.

No paid credentials, business impact, real customer deployment, human decisions or live model
transcripts were invented to close these gaps.
