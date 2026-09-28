# Portfolio release status

Current-state update: 2026-09-28 UTC. Historical release evidence retains its original dates. The owner approved the hiring-focused, MIT-licensed public release at
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

## Current development and deployment boundary

The [v0.2.0-rc.3 automated qualification candidate](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.2.0-rc.3) implements the owner's instruction that
execution be fully agentic or automated. Its [gate ledger](AUTOMATED-QUALIFICATION.md) separates
the pinned operator/reviewer exercise from current-source integration verification. The linked
release's `verification.json`, exact CI link and `SHA256SUMS.txt` identify the shipped code and evidence.
Implementation [CI 36443092813](https://github.com/ahines99/portco-data-onboarding/actions/runs/36443092813)
verified actual PostgreSQL publication and both frozen benchmark safety gates; final release evidence
includes a fresh full CI run for the final source.

- Separate delegated agents operated and reviewed the SAP-style workflow: six supported metrics,
  38 verified publication files, 46 intact audit events and one rejected unsupported mapping.
  Review was source-informed, not blinded or a human pilot.
- The six-case [v2 corpus](../evals/agent_qualification_v2/README.md) was frozen before evaluation.
  Its initial safety failure is retained. Entity-uncertainty remediation passes safety, with
  accuracy unchanged at 42/52 proposals and 42/43 positive targets covered. Review rises from
  22/52 to 48/52; ten incorrect proposals and ten unresolved fields remain.
  On the original v1 corpus, current-source review rises to [17/33](evidence/unfamiliar-benchmark-rc3.json)
  from the earlier 7/33, while 32/33 correctness, 32/32 target coverage and safety pass remain unchanged.
- The [PostgreSQL source connector](POSTGRES-SOURCE.md) implements bounded, read-only snapshots
  with explicit types/keys, verified remote transport requirements and atomic registration.
  Its actual PostgreSQL acceptance covers synthetic extraction through nine-metric publication.
  The [retained hosted report](evidence/postgres-source-acceptance.json) records 11 tables / 14,639 rows,
  59 publication files, 45 intact audit events and no waived checks.
- Agent observations led to review-packet evidence pointers, stage-appropriate context links
  and neutral reviewer wording. A separate follow-up verified links and retained authority checks.
- A prepared optional human-pilot kit and timing utility do not fabricate participation, consent,
  a manual baseline or savings. Free-only delivery remains GitHub Pages plus local/CI execution.

The stable portfolio release is [v0.1.1](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.1.1).
The published [v0.2.0-rc.1 candidate](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.2.0-rc.1)
adds production JWT verification, startup validation, readiness/resource controls and a Render/Auth0
recipe. It is not an accepted live service. Its verified baseline includes 553 non-PostgreSQL tests,
five dedicated PostgreSQL tests, 37 evaluation cases and ten passing CI jobs. Local and hosted test
populations overlap; these are dated candidate results, not guarantees about every future commit.

The `v0.2.0-rc.2` audit-response candidate adds the following evidence. Consult the
[release list](https://github.com/ahines99/portco-data-onboarding/releases) and each release's exact
CI/verification assets before describing a candidate as published or fully verified.

| Workstream | Evidence and boundary |
|---|---|
| External extract ingestion | [CSV snapshots](CSV-SOURCE.md): explicit types, source digests, tenant ownership and restart-safe registration; [synthetic smoke](evidence/csv-source-smoke.json) imported 11 tables / 14,639 rows and published nine metrics; no remote SaaS credentials or network connector |
| Operational input | [Public retail exercise](PUBLIC-OPERATING-DATA.md): 10,000 rows imported/profiled and six aggregate controls passed; no mapping, approval or financial publication |
| Generalization | [Frozen unfamiliar-schema benchmark](../evals/unfamiliar/README.md): separate-agent-authored cases and immutable labels; first post-change run failed safety with unchanged accuracy; post-benchmark remediation passes safety at 32/33 correct proposals, with remaining errors/abstentions; not external human evaluation |
| Business impact | [Operator pilot protocol](OPERATOR-PILOT.md) and blank evidence template prepared; no participating company, completed pilot or measured savings |
| Portfolio positioning | [Resume and claims matrix](RESUME-AND-CLAIMS.md), preserving AI-assisted ownership and limits |
| Live service | Owner selected free-only delivery on 2026-09-28. Provider access and real agent-token preflight passed; paid backend remains undeployed and [live acceptance](LIVE-DEPLOYMENT.md) unverified |

### Frozen benchmark and subsequent remediation

The [reconstructed baseline](evidence/unfamiliar-benchmark-baseline.json) and
[first post-change run](evidence/unfamiliar-benchmark-first-postchange.json) both produced 31 correct
mappings out of 33 proposals, covering 31 of 32 positive labeled targets. Entity outcomes were 10/10
including two appropriate no-match abstentions; joins were 3/3 and unit outcomes 5/6. Six of 33
proposals required review. The first post-change run **failed the safety gate**: a competing monetary
interpretation was not routed to review. Accuracy did not improve on these cases.

The cases/labels were frozen by a separate agent before mapper edits, and the original baseline was
later reconstructed from an isolated archive of the prior commit. The first result remains intact.
The [final rerun](evidence/unfamiliar-benchmark.json) is **post-benchmark remediation**, not a new
held-out evaluation. It passes the safety gate with 32/33 correct proposals (96.97% precision),
32/32 positive targets covered, 10/10 entity outcomes including two no-match abstentions, 3/3 joins
and 6/6 unit outcomes. Review burden rises from 6/33 (18.18%) to 7/33 (21.21%). One incorrect
review-required proposal and eight unresolved opaque fields remain. Passing safety does not make
the remaining proposal correct, prove uncertainty calibration or establish customer generalization.

Historical acceptance below closed the original synthetic portfolio scope. The owner subsequently
requested a live service; the old scope closure does not close that expanded requirement. Security
acceptance must use the [current image assessment](image-risk-assessment.md), not an old scan count.

## Final audit patch

The final three-agent review identified and reproduced review-packet binding, invoice consistency,
and annotation-provenance defects plus contradictory scope wording. Version 0.1.1 fixes these
with regression tests and adds an enforced fixable HIGH/CRITICAL image vulnerability gate.
See [audit closeout](FINAL-AUDIT-CLOSEOUT.md) and the exact tagged CI run linked from the
[release](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.1.1).
The verification below is historical v0.1.0 evidence; it is not a fresh v0.1.1 measurement.

## Historical v0.1.0 verification

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

## Historical portfolio-roadmap disposition

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

## Historical results that did not pass

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
