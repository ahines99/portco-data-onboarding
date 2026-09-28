# Roadmap from verified portfolio to externally validated workflow

Prepared 2026-09-28 against repository commit `03c4fb38b51364caf42cde2580a3e9bb933a505c`.
Execution amendment: the owner subsequently instructed, "Everything should be fully agentic or
automated." The active execution scope is therefore the
[automated qualification plan](AUTOMATED-QUALIFICATION.md). Agent-operated qualification replaces
the human-pilot completion gate; it does not establish human usability, consent, customer adoption
or savings. The human protocol below remains an optional future study, not a dependency on the
current automated execution. Free-only hosting remains binding.

Status: original plan retained for traceability; the linked automated qualification ledger governs
current execution and evidence. Statements below describe the original human-study design, not
completed participation or remaining owner obligations. The completed
[audit-gap implementation record](AUDIT-GAP-ROADMAP.md) and historical release evidence remain intact.

**The objective is to establish whether an independent person can use the existing workflow to
produce a correct, reviewed result, then build only the integration and usability improvements
that the exercise justifies.** The current free portfolio is already available. This plan does not
reopen completed work merely to accumulate more tests or architecture.

The owner selected free-only delivery. Keep GitHub Pages and local execution. No paid hosting,
identity upgrades, model calls, paid datasets, domains or trial-to-paid dependencies are authorized
by this roadmap. Use existing hardware and free local tooling; record any actual incremental cost.
Do not expose development authentication on the internet to obtain a free remote demonstration.
Remote deployment is an optional future decision, not a prerequisite for the local pilot.

**The starting point is verified engineering with incomplete external validation.**

| Area | Baseline | Remaining evidence |
| --- | --- | --- |
| Portfolio and local workflow | Public Pages site, CLI/MCP workflow, recorded demo, released packages | Independent setup and use |
| Ingestion | Typed CSV snapshots; synthetic full workflow; public historical retail profiling | Authorized operating extract and, if justified, one actual source connector |
| Mapping | Frozen benchmark remediation: 32/33 correct proposals, 32/32 positive targets, seven reviewed proposals, eight unresolved fields | New independent cases and first-run results before tuning |
| Governance and recovery | Separate reviewer authority, content-bound approvals, persistent execution and recoverable publication | Actual operator/reviewer experience and scoped acceptance |
| CI | Ten jobs passed on the baseline commit, including 37/37 golden cases | Relevant checks for each later change |
| Identity | Real Auth0 agent JWT verified; reviewer registration exists | Reviewer login/MFA and complete hosted acceptance, only if hosting is revisited |
| Business value | Pilot protocol and blank measurement record | Consent, observations, review effort, outcomes and permitted publication |

The original 0/10 probe and the later frozen benchmark are different experiments. Do not report
their scores as a single accuracy improvement. The final frozen score follows benchmark-informed
remediation. A new experiment must retain its initial results even if they fail.

**Ownership is explicit: Codex handles implementation and analysis; people supply permission,
independent judgments and actual observations.**

| Owner | Responsibilities |
| --- | --- |
| Codex | Prepare materials, implement bounded tooling, run authorized checks, diagnose defects, summarize observed evidence and maintain accurate public claims |
| Alex | Recruit participants, coordinate availability, identify an appropriate source, make product choices when genuine alternatives arise, and obtain permission to share outcomes |
| Data owner | Authorize source use, storage, retention, disclosure and deletion; approve any company identification |
| Independent operator | Perform the tasks, record effort and difficulties, disclose prior project involvement and confirm observations |
| Separate reviewer/domain owner | Define expected business outcomes before seeing proposals, inspect decisions and results, and sign their own acceptance |

The operator must be independent of implementation for an independent-use claim. Alex may fill
the reviewer role if qualified and separate from the run starter, but the report must disclose that
relationship and must not call that review independent of the project. Never substitute an agent
for a consenting human participant. Recruitment text can be drafted; no outreach is sent without
an explicit instruction naming the intended recipients/channel.

**Execution proceeds through gates rather than a promised launch date.**

| Phase | Deliverable | Dependency | Indicative focused effort |
| --- | --- | --- | --- |
| 0. Prepare | One pilot kit and a pinned reproduction baseline | None | 1-2 working days |
| 1. Observe | Consented local pilot and honest outcome report | Participant, source authorization, reviewer and frozen task | 1 day preparation, agreed sessions, 1 day analysis; scheduling additional |
| 2. Evaluate | Independent unfamiliar-schema evaluation v2 | Independent author/domain expectations | 2-4 working days after inputs are ready |
| 3. Integrate | One bounded read-only connector, if justified | Source selected from actual need; authorized access | 3-7 working days for a simple source; reassess after discovery |
| 4. Improve review | Minimal local review interface or targeted CLI improvements | Recorded pilot friction and integration decisions | 3-5 working days if a UI is justified |
| 5. Package | Updated evidence, release decision, case study and handoff | Completed results and required sharing approvals | 1-2 working days |
| Optional hosting | Accepted remote service | Actual remote-use need and a separately authorized viable hosting plan | Estimate only after provider and scope selection |

These estimates are planning ranges, not booked dates or elapsed-time guarantees. The connector
and UI may be deferred if evidence does not justify them. Recruitment and independent input can
dominate elapsed time. Evaluation preparation can run alongside recruitment; initial pilot results
must precede any claim that later product changes improved operator outcomes.

**Phase 0 makes the next session executable without adding new product scope.**

Codex will:

1. Pin a source commit, lockfile hash and environment description. Keep the current release
   evidence immutable and give later changes their own records.
2. Assemble a participant brief, short task card, local installation guide, unrelated synthetic
   training exercise and troubleshooting sheet. Link existing documentation instead of duplicating
   the operating protocol.
3. Prepare a private intake checklist for authorization, data minimization, storage, retention,
   operator/reviewer identities and permitted disclosures. Public records use opaque references.
4. Adapt the existing blank record into a per-session form and timer/event-log format, retaining
   null for missing measurements. Add an assistance log and deviation log.
5. Define a small task menu: ingestion/profiling only, mapping review, or supported financial
   onboarding. The selected task determines the claim; not every pilot needs all nine metrics.
6. Verify the documented install-and-demo path in an isolated environment and fix reproducibility
   defects. Preserve the command output and environment used; do not rerun all prior studies.

Alex will identify one operator and one separate qualified reviewer, suggest a permissible source,
and coordinate a session. Codex can draft a recruitment message, but Alex controls outreach.

Gate P0: one coherent kit; baseline pinned; installation path checked; no credentials or sensitive
records committed; no invented participant or outcome. Proposed artifacts: `docs/pilot-kit/` for
generic instructions and ignored `var/operator-pilot/<pilot-id>/` for private session material.
The existing [pilot protocol](OPERATOR-PILOT.md) and
[record template](evidence/operator-pilot/TEMPLATE.json) remain authoritative.

**Phase 1 records whether someone else can actually complete the workflow.**

Before execution, the data owner authorizes the exact use and the participants agree to the task.
Freeze input hashes, expected outputs, supported metrics, reference answers, task order, time cap,
completion rules and disclosure boundaries. Keep LLM calls disabled initially. If an external agent
client is used, its metadata disclosure requires separate authorization.

Prefer two matched tasks with counterbalanced manual/assisted order and comparable disjoint inputs.
If only one task is possible, label the exercise a feasibility observation and disclose learning
effects. Do not claim a causal productivity improvement from one participant.

Codex supplies the installation and recording tools and resolves technical blockers. Every
intervention is logged. The operator performs the task; the reviewer makes and records actual
decisions. No automated approvals substitute for pilot signoff. If the frozen version needs a
material fix, preserve the original attempt, label the new version and distinguish the retest.

Record operator and reviewer active time separately, setup/training, wall time, machine time,
corrections, review cycles, requests for help, missing mappings, failures, and actual costs.
Both manual and assisted arms must meet the same output contract. Failed tasks remain in the
completion denominator and have elapsed-to-stop time, not a fabricated successful completion time.

Gate P1: documented authorization; all started attempts accounted for; operator-confirmed logs;
reviewer-assessed correctness; integrity checks for any publication; and an outcome of completed,
partially completed, unsupported, stopped or withdrawn. No minimum time savings is required.
An unsuccessful pilot can satisfy evidence collection while preventing a usefulness claim.

Public deliverable, only if separately approved: a small aggregate report in
`docs/evidence/operator-pilot/`, stating task scope, participant count, effort, corrections,
assistance and limitations. Do not publish raw data, consent documents, identities or quotations
without the required permission. Follow the retention/deletion decision, including backups.

If no authorized operating extract is available, a human can use synthetic or public data for a
usability exercise. Describe that narrower result accurately; it is not customer adoption or a
validated company onboarding. If no human participates, continue preparation and evaluation tooling
but leave P1 unexecuted.

**Phase 2 tests new schemas before their outcomes influence development.**

Recruit an independent domain practitioner/case author. If only another agent authors the cases,
label that authorship explicitly and do not claim external human independence. A planning target
is 4-6 small cases; the source and expected outcomes matter more than maximizing the count.

Include unfamiliar terminology, unit ambiguity, competing monetary fields, missing or misleading
relationships, and fields with no defensible mapping. Use authorized or independently authored
inputs with documented provenance. Separate inputs from expected labels and freeze both with
hashes before inference changes. Keep the existing v1 corpus and reports unchanged.

Codex will extend the harness only where needed, pin the tested implementation, execute a first
run without consulting labels during inference, and produce a report covering mapping precision,
target coverage, units, joins, abstention, incorrect unreviewed decisions and review burden.
Report counts and denominators; keep heuristic confidence distinct from calibrated probability.

Gate P2: provenance and authorship disclosed; corpus and expected outcomes frozen; first-run
results preserved; no incorrect unreviewed decision permitted by the safety gate. Accuracy has no
arbitrary promised pass percentage. Safety failures block stronger deployment claims, but remain
valid experimental results. Later fixes get separately labeled remediation reports; they do not
replace the first run or become fresh held-out evidence. Further generalization claims require
additional untouched cases.

Proposed deliverables: a versioned corpus under `evals/` and separate initial/remediation reports
under `docs/evidence/`. Any sensitive corpus remains private, with shareable manifests redacted.

**Phase 3 adds one connector only after identifying a useful source.**

Choose from actual pilot need and available authorized access. Do not select Salesforce, SAP,
NetSuite or another product merely for its name. A read-only database used by the participant may
be a better first integration than a large SaaS API. No paid account or expiring paid dependency
is assumed. Lack of permitted access blocks live connector acceptance, not unrelated work.

The first connector is an operator-triggered, bounded snapshot extractor that feeds the existing
source contract. It is not a synchronization platform. Reuse immutable snapshots and workflow
review controls rather than bypassing them.

Minimum scope:

- Least-privilege read-only credentials in an approved local secret mechanism; no values in Git,
  command output, error messages or publication artifacts.
- Explicit allowed objects/columns, company ownership, declared types and extraction bounds.
- Stable extraction metadata: source/version, extraction time, filters, row counts and digests.
- Bounded pagination and timeouts; rate-limit/retry handling where the source requires them.
- A documented consistency model. Use an available snapshot/as-of capability or disclose that
  the extract can change while pagination runs; never claim consistency merely from final hashes.
- Schema-change detection and fail-closed handling of unsupported changes or partial extraction.
- Atomic registration after a complete snapshot; interrupted work must not appear as a valid source.
- Tests for authentication failure, interruption, duplicates/missing pages, schema changes, type
  precision, secret redaction and company isolation, as applicable to the chosen source.

Gate P3: authorized real-source extraction, bounded and reproducible provenance, no source writes,
and the agreed downstream task completed or honestly reported unsupported. Mock-only checks
establish implementation behavior, not live integration. Incremental sync, writes, CDC, scheduling
and additional vendors are excluded from this first connector.

**Phase 4 improves the review experience in response to observed friction.**

First determine whether better packet formatting and CLI guidance solve the pilot's problems.
Build a browser interface only if it addresses recorded difficulty. The initial UI, if selected,
is a local operator tool bound to loopback, retaining the trusted-local-operator boundary.

Minimum useful screens are pending runs, mapping/evidence review, test failures, certification and
publication result. Reviewers need to see source and target meaning, units, transforms, reason for
review, evidence and the exact subject hash. Decisions must distinguish approval, rejection and
required corrections. Financial failure controls cannot be hidden behind default bulk approval.

All decisions pass through existing backend policy and stale-packet checks; never edit workflow
tables directly. Add appropriate request-origin/CSRF protections if browser sessions/cookies are
used, avoid exposed bearer tokens, and test hostile local-web requests. A local UI does not become
a remote multi-user security boundary by changing its bind address.

Gate P4: an operator/reviewer can complete the agreed review task; stale packets and unauthorized
approvals fail; evidence and reasons are understandable; keyboard and visible error behavior work.
Record the validation session separately from the original pilot, including repeat-user learning
effects. A remote UI and full OAuth login experience are separate deployment work.

**Security and reproducibility maintenance run alongside these phases.**

Use current dependency/image evidence when application or image changes require it. Fix actionable
findings and document residual preconditions and limitations; a passing fixable-vulnerability gate
does not accept all residual risk. Run checks proportional to the changes, followed by the required
release checks on the exact candidate commit. Preserve distinct reviewer authority, company scope,
approved-content hashes, source read-only access and deterministic monetary calculations.

Do not combine privacy approval, reviewer certification and permission to publish a participant's
story into one assumed consent. Unknown measurements remain null; observed failures remain visible.

**Phase 5 turns completed work into a coherent portfolio release.**

Codex will reconcile README, Pages, case study, release status, handoff and resume guidance with
the new evidence. Link the initial failed attempts and remediation where relevant. Separate
implementation, automated verification, independent use and business-impact claims.

Verify the installation path, changed functionality, golden evaluations, security controls,
packaging and container behavior appropriate to the release. Build distributions, attach
checksums and evidence, and associate them with the exact source and CI run. Make an explicit
stable/prerelease decision based on compatibility and known defects; completing a pilot does not
automatically make a deployment candidate production accepted.

Alex and the participant/data owner approve any proposed identities, quotes and external findings
before public use. If sharing is not authorized, keep the report private and publish only approved
technical changes and claims. Personal authorship statements remain accurate about AI assistance.

Gate P5: coherent documentation, verified release artifacts, traceable checks and no unsupported
claim of time savings, customer adoption, generalization, compliance or live production operation.
The portfolio remains useful even when the measured result is mixed or a connector/UI is deferred.

**Remote hosting remains a separate optional decision.**

Revisit it only when an identified user needs remote access. Compare a viable free arrangement
against the actual workload and durability needs; otherwise retain local use. A paid plan requires
new spending authorization, and an expiring database or disposable filesystem is not a durable
production substitute. Do not weaken authentication or reviewer controls to fit a free tier.

If a viable arrangement is selected, complete the reviewer identity flow, HTTPS and authorization
denials, certified synthetic workflow, actual runtime assessment, restart persistence, coordinated
restore, monitoring and rollback checks in [LIVE-DEPLOYMENT.md](LIVE-DEPLOYMENT.md). Until then,
retain the claim "production deployment controls implemented; live acceptance incomplete."

**The first execution batch is bounded and unblocked.**

Codex's first batch is Phase 0: assemble the kit, prepare blank recording materials, document the
task choices and verify setup. Alex's first batch is identify one independent operator, one separate
reviewer and one permissible source, then coordinate availability. No billing change is requested.
No participant answer is required to begin generic preparation, but consent and source authorization
are required before dependent pilot work.

Track each work item as planned, ready, in progress, awaiting named external input, completed or
deferred. Record the evidence link and reason for each status. "Completed" means its gate is met;
"deferred" does not mean accepted, and an unexecuted pilot never acquires a successful outcome.
