# From synthetic source schemas to certified metrics

**Portfolio Company Data Onboarding Agent** · Alex Hines · Python / dbt / DuckDB / PostgreSQL / MCP

This portfolio project explores a practical data engineering problem: a portfolio-company schema
does not automatically share the definitions, units or data quality expected by an investor's
reporting model. A plausible-looking column mapping can produce a financially wrong answer.

The demonstration uses synthetic SaaS and SAP-style fixtures. It has no production customers,
measured analyst-time savings or investment-performance claim. The implementation was developed
with substantial AI assistance. Alex approved the personal statement and delegated final acceptance;
[the record](FINAL-ACCEPTANCE.md) distinguishes owner approval from automated execution.

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

The earlier audit baseline passed 451 non-Postgres tests and four PostgreSQL tests. The release
adds packaging and test-isolation coverage; the release status and linked CI run contain the final
counts. Coverage of the metric reference module is 100%; this is not whole-application coverage.
Fixture accuracy does not establish accuracy on a new real company. The timing sample is neither
a scalability benchmark nor proof of business time savings.

The [additional unfamiliar-schema probe](evidence/heldout-probe.json) matched **0 of 10 labeled
targets** because it produced no proposals. It reached a certification review with no accepted
source mappings; no reviewer approved or published the probe. This exposes dependence on recognized
schema vocabulary. The probe is small and was authored by the implementation assistant, not an
external blinded evaluator. No mapper rules were tuned after observing the result.

## Boundaries and next steps

The source adapter targets DuckDB fixtures; publication targets a local directory. Static HTTP
tokens and trusted local reviewer identities are development controls. There is no public live
MCP backend, production identity provider or live warehouse deployment. The local semantic executor
supports a defined monthly subset; actual MetricFlow compatibility is tracked separately.

Six real model sessions and a captioned synthetic-voice tour have now been collected. The
[owner-approved acceptance packet](ASSISTED-ACCEPTANCE.md) and [final acceptance](FINAL-ACCEPTANCE.md)
record completed delegated mapping/certification and accepted annotation/personal wording. Independent
first-use feedback is optional future validation.
Broader schema coverage, independent usability feedback and stronger controlled model studies are
possible next steps. They would extend the evidence beyond the accepted synthetic portfolio scope.

## Interview prompts

Explain how cents become dollars; trace one metric through evidence, mapping, reconciliation and
certification; explain why role names alone do not secure an operator-controlled machine; describe
recovery after a crash between rename and commit; explain what a perfect fixture score cannot prove.

Suggested portfolio description: “A governed data-onboarding prototype that profiles synthetic
portfolio-company sources, proposes evidence-linked mappings, generates dbt models, reconciles
financial metrics and publishes only after separate reviewer certification.” The
[owner-approved personal statement](ASSISTED-ACCEPTANCE.md) describes Alex's role and substantial
AI assistance without claiming production outcomes or sole implementation authorship.
