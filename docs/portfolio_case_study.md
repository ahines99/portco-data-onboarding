# From synthetic source schemas to certified metrics

**Portfolio Company Data Onboarding Agent** · Alex Hines · Python / dbt / DuckDB / PostgreSQL / MCP

This portfolio project explores a practical data engineering problem: a portfolio-company schema
does not automatically share the definitions, units or data quality expected by an investor's
reporting model. A plausible-looking column mapping can produce a financially wrong answer.

The complete financial demonstration uses synthetic SaaS and SAP-style fixtures. A later
[public retail exercise](PUBLIC-OPERATING-DATA.md) adds real historical ingestion/profiling evidence,
without financial certification. It has no production customers,
measured analyst-time savings or investment-performance claim. The implementation was developed
with substantial AI assistance. Alex approved the personal statement and delegated final acceptance;
[the record](FINAL-ACCEPTANCE.md) distinguishes owner approval from automated execution.

## Current automated qualification release

The owner selected fully agentic or automated execution and free-only operation. The
[automated qualification plan](AUTOMATED-QUALIFICATION.md) adds a separately authored six-case
corpus, a read-only PostgreSQL source connector, and recorded separate operator/reviewer agent
work. Actual PostgreSQL acceptance passed on `25c6937` in
[hosted CI](https://github.com/ahines99/portco-data-onboarding/actions/runs/36443092813).
The [v0.2.0-rc.3 release record](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.2.0-rc.3)
and [release status](RELEASE-STATUS.md) identify integrated verification and exact release provenance.
These additions do not establish a production deployment or independent human validation.

## The problem made concrete

One source stores invoice-line amounts in cents while invoice headers use dollars. Another calls
a CRM opportunity amount `rev`, despite it representing potential bookings rather than recognized
revenue. The workflow profiles metadata and aggregates, proposes an evidence-linked mapping and
stops for review. A model cannot turn those proposals into certification by saying “approved.”

The output is a tested dbt project, semantic metric definitions, a reconciliation report and a
versioned local publication carrying the certification metadata. Monetary calculations execute in
deterministic code; the nine generated metrics include ARR, MRR, billings, recognized revenue,
COGS, OPEX, EBITDA, gross-margin percentage and active customers.

## Engineering decisions

| Decision | Why it matters | Evidence |
|---|---|---|
| State lives in the database | A lost conversation or restarted process must not lose review state | Engine tests; container restart/recreation checks |
| Models call typed MCP capabilities | Principal checks and contracts constrain available actions | MCP integration and permission evals |
| Financial math is deterministic | Plausible prose is not a reconciliation | Independent reference calculators and generated semantic execution |
| Approval binds a content hash | Changing a mapping must invalidate what was reviewed | Stale-approval and resume/configuration regressions |
| Publication has prepared/complete states | Filesystem rename and database commit can fail separately | [Recovery ADR](adr/0012-recoverable-publication.md) |
| Profiles restrict category disclosure | A low-cardinality value can still be a person's name | Explicit per-column approved category domains |
| Optional model judge defaults off | Additional model calls need demonstrated value | Recorded/replay comparison harness; no live uplift claimed |

## A consequential failure and repair

The audit reproduced a publication failure window: a database receipt could exist even when the
directory rename had failed. Reusing the receipt then appeared successful while files were absent.
The repair introduced a durable prepared state, reserved version, exact file verification and retry
recovery. Certification and execution ownership are rechecked at finalization. The tests cover both
rename-before-commit and receipt-before-rename failure windows, cancellation, concurrent finalizers
and changed files. This is a useful interview example of correctness across two persistence systems.

## Inspect the results

- [Successful report](evidence/success-report.md): mappings, evidence, tests and publication.
- [Failure report](evidence/failure-report.md): malformed source stops at review.
- [Reconciliation details](evidence/reconciliation.json): actual generated metric checks.
- [Upgrade/restore rehearsal](evidence/recovery.json): populated local state survives migration and restoration.
- [Timing sample](evidence/benchmark.json): three cold/reused fixture runs, excluding human waiting.
- [Scripted demo transcript](evidence/demo-transcript.txt) and [read-only replay](index.html).
- [Release evidence and accepted scope](RELEASE-STATUS.md).
- [Separate-agent operator attempt](evidence/agent-operator-qualification/README.md) and
  [reviewer completion](evidence/agent-reviewer-qualification/README.md) on baseline `03c4fb3`.
- [Automated release qualification](AUTOMATED-QUALIFICATION.md),
  [PostgreSQL contract](POSTGRES-SOURCE.md) and [v2 corpus](../evals/agent_qualification_v2/README.md).

The [release status](RELEASE-STATUS.md) and exact tagged CI/verification assets contain dated test
counts. Local and hosted populations overlap and must not be added together. Coverage of the metric reference module is 100%; this is not whole-application coverage.
Fixture accuracy does not establish accuracy on a new real company. The timing sample is neither
a scalability benchmark nor proof of business time savings.

The [additional unfamiliar-schema probe](evidence/heldout-probe.json) matched **0 of 10 labeled
targets** because it produced no proposals. It reached a certification review with no accepted
source mappings; no reviewer approved or published the probe. This exposes dependence on recognized
schema vocabulary. The probe is small and was authored by the implementation assistant, not an
external blinded evaluator. The historical probe was not tuned to make that recorded result pass. Later development adds
reviewed structural inference and a [frozen separate-agent benchmark](../evals/unfamiliar/README.md).
That benchmark has distinct inputs, immutable labels and separate baseline/candidate reports; it is
not external human validation or fully blinded research. Its results do not replace the original failure.
The [first post-change run](evidence/unfamiliar-benchmark-first-postchange.json) matched 31 of 33
proposals (31 of 32 labeled targets), unchanged from the reconstructed baseline, and failed its
safety gate for an unreviewed competing monetary interpretation. Later fixes/reruns are
post-benchmark remediation, not held-out proof of improvement. The [remediation rerun](evidence/unfamiliar-benchmark.json)
passes safety with 32/33 correct proposals, 32/32 positive targets covered and 6/6 unit outcomes.
Review burden increases to 7/33; one incorrect reviewed proposal and eight unresolved opaque
fields remain. Those counts describe the preserved historical remediation. The [current v1
regression](evidence/unfamiliar-benchmark-rc3.json) after the later entity-uncertainty repair retains safety, 32/33 correctness and 32/32
target coverage, with 17/33 proposals requiring review and eight unresolved fields.
Those limits matter as much as the passing safety gate.

A new six-case [agent-authored v2 corpus](../evals/agent_qualification_v2/README.md) preserves another
first safety failure. Both its initial and remediated runs produced 42/52 correct proposals and
covered 42/43 positive targets. The repair propagates uncertain entity interpretation into
column review: review rises from 22/52 to 48/52 and safety passes, with ten incorrect proposals
and ten unresolved fields still disclosed. This improves the review boundary, not mapping
accuracy. The new corpus is separate-agent authored, not an external human study; remediation is
feedback-informed and cannot be called untouched held-out validation.

## Separate agent operation and review

An operator agent used the documented CLI against pinned baseline `03c4fb3`, exported the SAP-style
mapping packet, observed a denied same-starter review attempt and handed off the run. A separate
delegated automated reviewer inspected the packet, aggregate evidence, ontology and fixture source.
It explicitly rejected `FKART` as invoice lifecycle status and approved the other reviewed items;
no blanket default approval or failed-check waiver was used.

The [completed run](evidence/agent-reviewer-qualification/README.md) published **six supported metrics**,
verified **38 publication files** and an audit chain of **46 events**. It is distinct from the
nine-metric SaaS demonstration. Unsupported metrics remain `NEEDS_EVIDENCE`; the reviewer saw fixture
answer-key entries during source inspection, so the exercise is source-informed and not blinded.
Both identities were controlled locally. Command durations are machine/agent execution observations,
not human active time, independent usability measurements or business savings.

## Boundaries and next steps

Accepted source evidence includes DuckDB fixtures and [operator-imported typed CSV snapshots](CSV-SOURCE.md).
The [PostgreSQL source connector](POSTGRES-SOURCE.md) checks
SELECT-only authority and schema contracts, extracts a bounded read-only repeatable-read snapshot,
and registers it atomically through the CSV/DuckDB contract. Actual PostgreSQL acceptance extracted
11 synthetic tables / 14,639 rows, then removed the source database before onboarding. The snapshot
completed nine-metric reconciliation and publication with 58 generated-file hashes checked,
59 published files, 45 verified audit events and zero waived checks. The separate reviewer identity
in this smoke is scripted automation, distinct from the source-informed SAP-style agent review above.
It is operator-triggered extraction, not continuous synchronization or customer-system access.
Publication remains a versioned local directory. A 10,000-row public retail extract passed six ingestion/profile
controls, retaining missing identifiers, cancellations and negative quantities; no mapping was
approved or certified. Static HTTP tokens and trusted local reviewer identities are development
controls. A [production JWT candidate](LIVE-DEPLOYMENT.md) is implemented, but there is no accepted
public live MCP backend or live warehouse deployment. Auth0 agent-token verification is a separate
milestone; it does not accept the full hosted reviewer/identity workflow. The local semantic executor
supports a defined monthly subset; actual MetricFlow compatibility is tracked separately.

Six real model sessions and a captioned synthetic-voice tour have now been collected. The
[owner-approved acceptance packet](ASSISTED-ACCEPTANCE.md) and [final acceptance](FINAL-ACCEPTANCE.md)
record completed delegated mapping/certification and accepted annotation/personal wording. Independent
human first-use feedback remains optional future validation.
The [operator pilot protocol](OPERATOR-PILOT.md) defines consent, source minimization, paired
manual/assisted tasks, review burden, correction rates and actual participant signoff. It has not
been executed. At the owner's request, the active roadmap uses automated qualification instead.
The public presentation stays on free GitHub Pages and the workflow runs locally. Live hosting
acceptance and independent human/customer evidence remain unverified; neither public data nor
separate automated reviewers establish those outcomes.

## Interview prompts

Explain how cents become dollars; trace one metric through evidence, mapping, reconciliation and
certification; explain why role names alone do not secure an operator-controlled machine; describe
recovery after a crash between rename and commit; explain what a perfect fixture score cannot prove.

Suggested portfolio description: “A governed data-onboarding prototype that profiles synthetic
portfolio-company sources, proposes evidence-linked mappings, generates dbt models, reconciles
financial metrics and publishes only after separate reviewer certification.” The
[owner-approved personal statement](ASSISTED-ACCEPTANCE.md) describes Alex's role and substantial
AI assistance without claiming production outcomes or sole implementation authorship.

For role-specific wording and the boundary of each claim, see [the resume and claims matrix](RESUME-AND-CLAIMS.md).
