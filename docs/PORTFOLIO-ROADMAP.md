# Portfolio finalization roadmap

Date: 2026-09-27. Status: planning complete; the tasks below have not been executed by this roadmap.
Owner names: **Codex** means implementation, investigation, testing and preparation I can perform;
**Alex** means your decisions, account access, independent human reviews and publication choices.

This is the current remaining-work plan. [ROADMAP.md](ROADMAP.md) remains the historical build plan;
its unchecked acceptance bullets are not a reliable list of missing implementation.

## 1. Target and finish line

Working assumption: the primary audience is AI/data engineering hiring reviewers, with enough
business context for a PE operating team to understand the use case. A finalized portfolio release
should let a reviewer understand the problem in one minute, see the controls work in four minutes,
and reproduce the synthetic demonstration from a tagged checkout without paid credentials.

The release should demonstrate engineering judgment: deterministic financial calculations,
evidence-linked recommendations, human approval boundaries, durable workflow state, realistic
failure handling, and honest evaluation. A production warehouse integration, custom web UI and
publicly reachable MCP service are outside the default finish line.

Release criteria:

- A shareable repository, intentional license, clean committed release and green hosted CI at the release SHA.
- A tested credential-free quickstart, installed-package path and Docker path with explicit support boundaries.
- A recorded real agent/MCP session with Alex making the independent reviewer decisions.
- The planned paired Skill study completed and honestly reported; unresolved efficacy is labeled as such.
- A short case study, readable sample outputs, architecture graphic and captioned demonstration.
- Every numerical/security claim has a scope, date and evidence link; limitations are visible.
- Upgrade, reset and recovery instructions work on disposable data and protect unrelated state.
- Optional judge and MetricFlow claims are either validated or explicitly marked experimental/deferred.

## 2. Established baseline and evidence limits

The [remediation record](REMEDIATION-2026-09-27.md) records 451 non-Postgres tests, four PostgreSQL
14.24 tests, 37/37 eval cases, 100% branch coverage of the metric reference module, and a passing
installed-wheel demo. These are prior local results, not a fresh run for this planning exercise.
All 19 numbered audit findings have implemented fixes. This plan does not reopen them without evidence.

The remaining gaps include new release-readiness observations:

| Observation from the repository | Consequence | Task |
|---|---|---|
| Audit/remediation changes remain uncommitted; `git remote -v` is empty | No immutable, externally reviewable release or hosted CI result | PF-01, PF-05, PF-19 |
| No root license, changelog or contribution/security guidance; package metadata lacks project links/license | Distribution intent and reviewer navigation are incomplete | PF-02, PF-19 |
| No `.dockerignore` | Docker build context can include `.env`, local databases, Git history and virtual environments; this is not proof those files enter the image | PF-03 |
| Compose names a volume for `/data`, but no explicit PostgreSQL data volume | Full stack recreation has no documented, reliable database persistence contract | PF-04 |
| PostgreSQL fixture executes `DROP SCHEMA public CASCADE` against the supplied test URL | A mistaken URL can destroy unrelated database content | PF-03 |
| Container smoke stops at Gate A and restarts only MCP | Full container publication and stack recreation remain untested | PF-04 |
| Wheel smoke synchronizes all extras first | Base installation and minimal dependency completeness remain unproven | PF-06 |
| Demo script still says 17/17; architecture says one override and links only ADRs 0001–0010 | Presentation contradicts the latest 26-check demo and ADR-0012 | PF-08 |
| Walkthrough asks for an override to an already proposed target; demo auto-uses reviewer fixtures | Current scripted output does not establish an independent live human review | PF-08, PF-10 |
| Generated contract docs assert no field can carry row values; profile contracts can carry approved categories | Privacy language needs precise disclosure boundaries | PF-08 |
| Skill transcript tooling exists, but no live paired transcripts | Dynamic Skill usefulness remains an open original acceptance item | PF-11 |
| Judge model identifier and rate table are unverified live; unknown rates default to zero cost | Model compatibility and cost claims need verification before a paid run | PF-12 |
| Local semantic executor covers a supported monthly subset; actual MetricFlow has not run | Generated YAML execution is not proof of MetricFlow runtime compatibility | PF-13 |
| No committed recording, screenshots, curated sample report or portfolio case study found | Reviewers must run the project to see its best evidence | PF-09, PF-15, PF-16 |

## 3. Priorities and ownership

**Required** tasks define the recommended portfolio finish line. **Conditional** tasks become
required if we advertise the associated feature as supported. **Depth** tasks strengthen the piece
but can be deferred with an explicit limitation. Estimates are rough hands-on effort, not promised
elapsed time; access delays, CI failures and external compatibility work can extend them.

| ID | Task | Priority | Primary owner | Dependencies | Rough effort |
|---|---|---|---|---|---|
| PF-01 | Freeze scope and prepare reviewable commits | Required | Codex + Alex | None | 1–2 h |
| PF-02 | Repository identity, license and sharing decision | Required | Alex; Codex prepares files | PF-01 | 0.5–1.5 h |
| PF-03 | Distribution and destructive-test safeguards | Required | Codex | PF-01 | 2–4 h |
| PF-04 | Complete container persistence and workflow proof | Required for shipped Docker path | Codex | PF-03; Docker or hosted runner | 3–6 h |
| PF-05 | Hosted CI and durable evidence | Required | Codex; Alex supplies repository access | PF-02–04 | 2–4 h plus runner time |
| PF-06 | Minimal install and first-run usability | Required | Codex + Alex | PF-03 | 2–4 h |
| PF-07 | Migration, recovery and cleanup runbook | Required | Codex | PF-04, PF-06 | 2–4 h |
| PF-08 | Synchronize documentation and claims | Required | Codex | PF-01; refresh after other tasks | 2–4 h |
| PF-09 | Portable evidence bundle | Required | Codex | PF-05–08 | 1–3 h |
| PF-10 | Real agent-to-MCP demonstration | Required | Codex + Alex | PF-06, PF-08; agent session access | 1–3 h |
| PF-11 | Paired Skill usefulness study | Required for original acceptance | Codex + Alex | PF-10 | 3–6 h |
| PF-12 | Judge live validity and cost accounting | Conditional | Codex; Alex controls paid access | Model access and budget | 2–5 h |
| PF-13 | MetricFlow compatibility | Conditional | Codex | PF-06; compatible runtime | 2–6 h, investigate first |
| PF-14 | Generalization and performance evidence | Depth | Codex; Alex reviews domain assumptions | PF-09 | 3–6 h |
| PF-15 | Portfolio case study and interview narrative | Required | Codex drafts; Alex owns narrative | PF-09–11 | 2–4 h |
| PF-16 | Demo recording and visual assets | Required | Codex prepares; Alex records/reviews | PF-10, PF-15 | 2–4 h |
| PF-17 | Independent reviewer usability pass | Required | Alex or a chosen reviewer; Codex fixes | PF-06, PF-15–16 | 1–2 h plus fixes |
| PF-18 | Release security/dependency review | Required | Codex | Candidate release assembled | 1–3 h plus findings |
| PF-19 | Tag, release and portfolio publication | Required | Codex prepares; Alex authorizes destination | All required gates | 1–2 h |
| PF-20 | Maintenance and handover | Required, lightweight | Codex + Alex | PF-19 | 0.5–1 h |

## 4. Detailed execution tickets

### PF-01 — Scope and commit boundary

**Codex:** Inventory the final diff, keep historical audit evidence separate from current claims,
organize reviewable commits, and record an exact candidate SHA. Establish this file as the live
remaining-work tracker. Do not rebuild implemented features because old roadmap boxes are unchecked.

**Alex:** Confirm the audience and whether the intended outcome is a public hiring portfolio,
private interview repository or client demonstration. Identify any employer/client material that
must not be shared. The default scope is synthetic data, local publication and no public live backend.

**Done:** A scope statement and candidate commit exist; every remaining item has an owner and status.

### PF-02 — Repository identity and reuse terms

**Codex:** Prepare license text after your selection, package project URLs, short repository
description/topics, concise contribution instructions and an appropriate contact/security-reporting
path. Check that packaged resources and third-party assets have suitable attribution.

**Alex:** Choose the repository owner/name, visibility, reuse license or explicit private-only
distribution, and public author/contact identity. Provide the remote URL and authenticated access
through the local tooling. No password or token should be pasted into the roadmap or chat.

**Done:** Sharing terms and ownership are intentional; repository/package links resolve.

### PF-03 — Safe release tooling

**Codex:** Add `.dockerignore` for secrets, runtime state, caches and build noise while retaining
required runtime resources. Harden the PostgreSQL tests so they cannot reset an arbitrary database:
prefer a uniquely created disposable database/schema, explicit test opt-in and restricted ownership.
Add a regression proving an unrelated database/schema remains untouched. Review reset commands,
temporary cleanup and local ignore patterns for Windows and POSIX.

**Alex:** No routine action. Supply a dedicated disposable database only if a non-CI test server is used.

**Done:** Docker context excludes private state; PostgreSQL tests fail safely on an unapproved target;
cleanup is restricted to verified task-owned paths. This is higher priority than adding more features.

### PF-04 — Prove the container route

**Codex:** Give PostgreSQL an explicit named data volume, document local token setup, and run the real
Compose stack. Extend smoke coverage through separate agent/reviewer identities, certification and
publication; verify output and audit integrity. Test MCP restart and full stack down/up without
volume deletion, checking that both the database and artifacts survive. Document intentional reset
separately. Verify migrations and non-root writable paths inside the built image.

**Alex:** Provide either a working Docker runtime or repository access for hosted CI. You do not need
to install Docker locally if a hosted run supplies all required proof.

**Done:** Actual image/Compose execution passes, including publication and recreation persistence;
logs identify the commit/image and environment. Existing in-process HTTP tests alone do not close this.

### PF-05 — CI tied to the release

**Codex:** Push the prepared branch when publishing is authorized; run and fix all configured jobs:
lint/types, non-security tests, security tests, PostgreSQL 16, eval, demo, wheel and container smoke.
Store useful reports/artifacts, provide stable run links, and set explicit minimal workflow permissions.
Add a supported-OS policy: Linux CI plus Windows smoke if Windows support is advertised; do not claim
macOS verification without a run. Configure required checks where repository settings allow it.

**Alex:** Enable repository/Actions access if necessary. Choose public vs private before publication.

**Done:** All required jobs pass against the same candidate SHA with no unexplained skipped gates;
the CI badge links to a real run. A configured workflow is not passing evidence.

### PF-06 — Installation and first-use proof

**Codex:** Test a fresh clone with frozen dependencies and no local `.env`, then a wheel with only
base runtime dependencies outside the checkout. Verify CLI and stdio MCP entry points; independently
check optional extras needed for PostgreSQL, judge and telemetry. Build an sdist and test building its
wheel if an sdist is distributed. Add copyable PowerShell and POSIX instructions for fixtures, review,
certification, audit and Compose tokens. Make prerequisites and expected pause/output explicit.

**Alex:** Later perform the first-use pass in PF-17; no implementation work is expected from you.

**Done:** A reviewer can follow documented commands from a clean environment; optional dependencies
do not silently mask missing base requirements. Record setup time and failures without calling them benchmarks.

### PF-07 — Operational handoff

**Codex:** Write `docs/operations.md` covering migration 0003, backup of database plus artifacts,
upgrade of a populated pre-0003 disposable store, restore verification, pause/resume, expired
approvals, configuration-triggered rewind, failed publication and integrity failures. Explain the
trusted local reviewer/OS boundary. Add conservative dry-run cleanup for stale staging or document
manual inspection; never delete a publication merely because it is old. Distinguish reset from restart.

**Alex:** If retaining existing demo state, decide whether it needs preservation; production data is
outside this release. Review the human gate instructions from an operator's perspective.

**Done:** A populated upgrade and backup/restore rehearsal preserve run, approval, publication and
audit relationships. Recovery instructions name the observable state and next safe action.

### PF-08 — Documentation and claims consistency

**Codex:** Refresh demo script, architecture sequence/state diagrams, ADR links, threat model,
walkthrough, contract-doc generator and acceptance ledger. Remove the stale 17/17 check count,
no-op override story and unconditional upstream-reuse claim. Explain approved category disclosure,
deterministic row-reading reconciliation, nine generated versus 18 ontology metrics, and the exact
scope of 100% coverage. Explain that scripted fixture approvals are synthetic and local reviewer
identities depend on a trusted operator. Replace unsupported business claims such as weeks saved
with a motivation or clearly labeled hypothesis. Keep the baseline audit historically unchanged.

**Alex:** Confirm business terminology and approve only claims you can explain and defend.

**Done:** README, diagrams, demonstration and generated docs agree with the tagged code and actual
results. Any test counts are dated and scoped; generated docs still regenerate cleanly.

### PF-09 — Evidence someone can inspect without running code

**Codex:** Create a small `docs/evidence/` collection: readable successful run report, failed-run
report, selected mapping review/evidence, metric reconciliation, certification metadata and audit
verification. Include a representative generated dbt model and semantic definition. Add a manifest
with commit, dependency/fixture versions, commands, dates and checksums. Remove machine-specific
paths and secrets from shareable copies while preserving raw evidence privately and explaining edits.

**Alex:** Review material intended for public sharing, especially anything later added from live sessions.

**Done:** README links open readable examples; reviewers can trace one metric from mapping through
tests and approval to publication. Large databases/runtime directories are not committed as evidence.

### PF-10 — Live agent and independent human gates

**Codex:** Prepare the exact prompt/scenario and verify the documented MCP/Skill setup. Capture real
tool calls, evidence reads and agent responses. Use separate agent-only and reviewer channels; show
a gate denial, a genuine review decision, sandbox output, certification and publish. Troubleshoot the
client connection and retain failures rather than replacing them with a scripted transcript.

**Alex:** Make an authenticated agent client available. Inspect and submit the actual mapping and
certification decisions through the reviewer channel. Approve a suitable transcript excerpt for sharing.
These human decisions cannot be substituted by me merely switching to a reviewer principal.

**Done:** A real reproducible session at a recorded SHA demonstrates the agent stopping for your
review and continuing afterward. The deterministic G31 trace remains supporting test evidence.

### PF-11 — Skill usefulness, with honest outcomes

**Codex:** Use the existing comparison protocol to prepare three fixed prompt pairs, six fresh
sessions, constant model/settings/tools and alternating condition order. Collect full transcripts,
validate the manifest, score reviewed annotations and write a short result/limitations section.
If the study shows no difference, report that; propose targeted Skill changes and a separate new
evaluation set rather than selectively rerunning favorable examples.

**Alex:** Provide access for the sessions and independently review or appoint a reviewer for all six
transcripts, preferably with condition labels hidden. Annotate violations using the existing rubric.

**Done:** Six authentic transcripts, human annotations, hashes and a scored report exist. A small
study supports descriptive observations only. If it cannot establish dynamic usefulness, retain the
open acceptance item or explicitly narrow the portfolio claim; do not call the original item passed.

### PF-12 — Optional judge and paid-run accounting

**Codex:** Before any paid run, verify an available model identifier, supported request schema and
current pricing from the provider. Fix unknown-price handling so it reports unknown rather than
zero dollars. Separate judge token/cost accounting from the external coding-agent session cost.
Run one bounded connectivity check, then recorded baseline/judge comparisons on fixtures and held-out
challenges. Report accuracy, abstention, all populated confidence cohorts, latency, tokens and estimated
cost with pricing date. Retain failure/no-improvement outcomes and leave defaults off unless justified.

**Alex:** Decide whether this experiment belongs in the release; provide credentials through a secret
store/environment and a hard spending ceiling before calls. No paid calls are authorized by this plan.

**Done:** Either a real dated comparison and usable opt-in path exist, or the feature is explicitly
experimental with no benefit/cost claims. A negative result is acceptable evidence; fabricated uplift is not.

### PF-13 — Semantic runtime support boundary

**Codex:** Investigate a compatible pinned MetricFlow environment separately from the working lockfile.
Validate generated configurations and execute the supported metrics through the actual runtime;
compare monthly outputs to independent truth including zero revenue. Record unsupported metrics,
dimensions and time grains. If compatibility would substantially expand scope, retain the local executor
and document generated definitions as not yet runtime-certified.

**Alex:** Choose between full MetricFlow support and an explicit deferral after the compatibility findings.

**Done:** A runtime report supports the advertised compatibility, or README/acceptance scope clearly
limits it. Do not claim MetricFlow runtime proof from dbt parsing or the local YAML executor.

### PF-14 — Generalization and bounded performance study

**Codex:** Add an independently designed held-out schema/answer key without tuning against its labels.
Include new naming, missing inputs and ambiguous financial columns. Freeze mapping rules before the
run; report all outcomes and uncertainty. Measure cold versus reused runs, fixture row/table counts,
step times and resource use on stated hardware using repeated runs. Separate automated compute from
human waiting and distinguish fixed synthetic tests from real-world accuracy.

**Alex:** Optionally supply domain feedback or a sanitized schema you are authorized to share; no
real company records are required. Validate the financial meaning of the answer key where possible.

**Done:** A modest benchmark/generalization report has methods and limitations. Optional for release;
without it, avoid broad accuracy, scale or analyst-time-savings claims.

### PF-15 — Case study and interview story

**Codex:** Draft `docs/portfolio_case_study.md`: business problem/persona, source-to-certified-output
example, architecture, why calculations are deterministic, where model reasoning helps, approval and
privacy boundaries, evaluation, one consequential defect/fix, tradeoffs and next steps. Produce a
short portfolio-card description and evidence-backed resume bullets. Explicitly identify synthetic
data, AI-assisted implementation and your actual role rather than inventing ownership or impact.

**Alex:** Supply your motivation, target role and actual contribution; edit the first-person narrative.
Practice explaining one source-to-metric path, one failure recovery and one rejected design choice.

**Done:** The narrative is understandable to a technical reviewer and a business stakeholder, with
links to working evidence and no unsupported revenue, adoption or productivity claims.

### PF-16 — Recording and visual presentation

**Codex:** Prepare a timed three-to-four-minute script, legible architecture graphic, exact demo
commands and reset instructions. Select actual output screenshots and add alt text/captions. Provide
a short fallback clip from recorded output, clearly labeled; prepare a static preview if useful.

**Alex:** Record narration/screen or approve a screen-only presentation. Choose the hosting destination
and review the final cut. Show the live human-review moment; do not stage an automated approval as yours.

**Done:** A captioned video and a few readable screenshots are linked prominently from the README.
A busy reviewer sees the problem, trap, human control, calculation, failure path and outcome quickly.

### PF-17 — Independent first-use and credibility review

**Codex:** Prepare a short checklist and capture friction; fix reproducible issues and rerun affected
checks. Ask the reviewer to find the demo, explain supported scope and reproduce a run using docs alone.

**Alex:** Do this in a fresh environment or ask another person. Check whether the business value is
clear, the instructions work, the evidence is convincing and you can explain the implementation.

**Done:** The reviewer completes the credential-free route without undocumented assistance; remaining
friction is fixed or explicitly documented. Record feedback separately from automated test results.

### PF-18 — Final release review

**Codex:** Scan tracked files and Git history for secrets before publication; review dependency and
container scan results with date/tool versions, triaging findings rather than promising zero risk.
Check license inclusion, distribution contents, workflow permissions and public sample data. Rerun
the final required gates on the candidate commit after material fixes. Preserve local unshared secrets.

**Alex:** If a real credential is found, revoke/rotate it through its provider; decide publication
restrictions for material you own. No such leak has been established by this planning review.

**Done:** No unresolved release-blocking finding; accepted limitations have rationale and owners.

### PF-19 — Publish a coherent release

**Codex:** Prepare release notes, changelog, version/tag, wheel/checksums if distributing binaries,
and links to CI, evidence, video and case study. Ensure version metadata matches the intended tag.
Present the finished release for the publication decision; then publish to the authorized destination.
Update repository description/topics and the portfolio entry when access is available.

**Alex:** Authorize public release/visibility and the destination after reviewing the concrete draft.
Provide portfolio-site access if needed. A hosted live application and package-index publication are
not required; a tagged repository and accessible demonstration satisfy this release scope.

**Done:** Shared URLs work outside your logged-in session, the release checkout is clean and reproducible,
and README/portfolio/video all point to the same final version.

### PF-20 — Keep the finished project credible

**Codex:** Leave a short maintenance checklist, dependency-update policy, commands to rerun evidence,
and explicitly deferred issues. Avoid introducing automatic paid runs or deployments.

**Alex:** Choose a lightweight review cadence and respond to feedback. If the project becomes an archive,
mark that status rather than letting stale claims imply ongoing production support.

**Done:** Another person can identify the supported version, reproduce evidence and understand what
would need updating after dependencies, model versions or pricing change.

## 5. Execution order and handoffs

| Phase | Codex actions | Alex actions | Exit condition |
|---|---|---|---|
| A — Establish release scope | PF-01; prepare PF-02; start PF-03 and PF-08 | Audience, repository visibility/license/identity | Reviewable local candidate and explicit scope |
| B — Close release tooling gaps | PF-03–07; full-stack and minimal-install checks | Repository access; Docker only if hosted route unavailable | Reproducible candidate with hosted verification |
| C — Gather authentic evidence | PF-09–11; investigate PF-12/13 if selected | Human reviews, six-session annotation, optional paid budget | Agent session and honest evaluation record |
| D — Package the story | PF-15–16; PF-14 if selected | Personal narrative, recording/review | Case study, evidence and video ready |
| E — Independent acceptance and release | PF-17–20; final CI and release draft | First-use review and publication authorization | Tagged, shareable portfolio release |

Critical path: repository access → candidate commits → hosted container/CI proof → real agent and
human reviews → evidence/recording → final acceptance → publication. Documentation and safe local
tooling work can proceed while access is arranged. Model experiments do not block the deterministic
demo, but missing Skill evidence must remain visible in the original acceptance ledger.

Planning range: approximately **30–60 hours of combined hands-on work** for required tasks, plus
optional studies and compatibility work. Your portion is roughly **5–10 hours**, mostly setup
decisions, human review, recording and final acceptance. This is a planning estimate; do not treat
the previous fast remediation run as evidence that live evaluations and external setup take minutes.

## 6. Your initial action list

1. Confirm the intended audience and public/private release preference.
2. Choose repository owner/name, license/reuse intent and public author identity; supply an existing
   remote URL or authorize creating the repository when that step is ready.
3. Make an authenticated agent client available for the live demonstration and six comparison sessions.
4. Reserve time for mapping/certification review and transcript annotation; nominate another reviewer
   if preferred. These are meaningful human checks, not rubber-stamp approvals.
5. Decide whether a paid judge experiment is included and set a budget before any calls; defer by default.
6. Choose a recording/portfolio destination when the prepared material is ready. No cloud backend is needed.

I can start PF-01 preparation, PF-03, PF-06–09 documentation/evidence preparation, and PF-15 drafting
without credentials or a paid service once you ask me to execute the roadmap. Repository publication,
live reviewer decisions and paid experiments remain dependent on the inputs above.

## 7. Deferred product work

| Deferred feature | When it becomes justified |
|---|---|
| Snowflake/other warehouse adapter; Airbyte provisioning | A real source requirement and credentials, with least-privilege and source-specific tests |
| Catalog or warehouse deployment | A target environment, environment-bound approvals, rollback and deployment evidence |
| OAuth/JWT, TLS, abuse/rate controls and managed secrets | Before exposing a live service to untrusted users |
| Reviewer web UI | Evidence that CLI/MCP review prevents the intended audience from completing tasks |
| Multi-company batch orchestration | A concrete volume/concurrency requirement and measured engine limits |
| Temporal/Prefect migration | Demonstrated operational need beyond the current persistent workflow |
| Production SLOs, alerting, external OTLP, disaster recovery | An actual hosted service with an operator and support commitment |
| Large-scale performance or statistical model efficacy claims | Representative data, a larger prespecified evaluation and sufficient repeated measurements |

These are not prerequisites for the scoped portfolio release. Promote them only through an explicit
scope change; otherwise they distract from finishing and publishing the evidence already earned.
