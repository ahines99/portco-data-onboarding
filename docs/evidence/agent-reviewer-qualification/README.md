# Automated reviewer qualification: synthetic SAP-style workflow

Executed 2026-09-28 against pinned application commit `03c4fb3`. This is a delegated **automated,
source-informed qualification**, not a human operator pilot, customer adoption, external audit or
blinded evaluation. A separate operator agent started the run; this agent inspected and entered
review decisions under a distinct application principal. The user authorized agentic execution.
Application role separation is exercised, but both identities remain under a trusted local operator.

## Observed result

Run `ebdbc80e-859c-4b3e-836b-afc3b3b4159e` completed as `portco_b/v0001`. The starter was
`qualification-agent`; mapping and certification reviewer was `qualification-reviewer`.
No `--default approve` command was used and no failed checks were waived.

- Ten mapping-gate items received explicit decisions: nine approvals and one rejection.
- `sap.VBRK.FKART -> invoice.status` was rejected. The approved profile category was `F2`, a billing
  document type, not an invoice lifecycle status. The generated invoice staging model omits FKART.
  [SAP's billing type documentation](https://help.sap.com/docs/SAP_S4HANA_CLOUD/a376cd9ea00d476b96f18dea1247e6a5/d96fb6535fe6b74ce10000000a174cb4.html)
  identifies F2 as a type of invoice; it does not establish a paid/open status.
- Amount decisions used `DECIMAL(14,2)` profiles, ontology major-currency requirements and the
  synthetic generator's price-times-quantity/header-sum/GL posting logic. Values were retained in
  major units; no speculative cents conversion was applied.
- Employee names remain deterministic hashes; birthdates are excluded. Hashing is not a guarantee
  of anonymity. No raw employee values were inspected for these decisions.
- dbt completed 22 models and 57 passing tests. All 16 reconciliation/structural checks passed.
- Seven certification decisions approved the exact bundle and six supported metrics: **billings,
  COGS, EBITDA, gross-margin percentage, OPEX and recognized revenue**. This run did not publish nine
  metrics. Eleven unsupported metric findings remain `NEEDS_EVIDENCE`; headcount is reference-only.
- All 37 generated files matched their expected content hashes. The additional `certification.json`
  matched bytes reconstructed from persisted receipt and certification packet: **38/38 publication
  files verified**, with an exact file-set check and no symlinks. The audit chain verified across
  **46 events**. [Machine-readable verification](verification.json) retains file hashes and IDs.

## Reviewed scope, not a universal accounting policy

The synthetic qualification approved the proposed soft-delete policy for two of 80 customer rows.
Staging retains rows with exclusion flags; the generated downstream scope excludes six of 255
invoices, leaving 249. Every retained invoice's line sum matched its header exactly (zero maximum
absolute discrepancy). Billings is therefore the reviewed active-customer invoice scope, while
GL-derived revenue/cost/margin metrics use the supplied ledger. These are not equal-scope billing
and revenue totals and must not be compared as if they were.

The supplied GL has no OPEX postings; its 12 monthly zero outputs reconcile to the fixture reference.
That is a fact about this synthetic extract, not evidence that a real company has no expenses.
A real deployment needs an accountable data owner to choose retention, historical billing and ledger
scope policies; the automated decision here does not approve those policies for customer data.

## Inspection and provenance

The reviewer inspected the frozen review packet, connection validation, aggregate schema profile,
join evidence, canonical mapping, ontology, synthetic generator arithmetic, generated SQL,
reconciliation results and exact certification packet before submitting decisions. An initial source
grep also displayed fixture answer-key mappings; this is deliberately disclosed rather than calling
the review independent or blinded. No raw employee identifiers, names or birthdates were read.

[Per-item decisions and rationales](decisions.json) retain the mapping judgments. Mapping approval
`0009f446-595e-4d70-a639-e001771c2129` binds subject
`0fab9f6df411995005b17e82e645ddb2d8c3175aae9f01526b503c0a664371d6`.
Certification `d8252cdd-758b-464b-8d2c-e282f60d8079` binds subject
`891f21d86ad0a4638eb99e7667b1de1965d89f5f7f2503ac04ace00d403dc078` and manifest
`6e43b98ec97bec3b439cf910868d76c75f7fa5cdee86a45d894adbb504c582dd`.

Commands, full packet exports, logs, report, approvals and source profiles remain under ignored
`var/agent-reviewer-qualification`. Reviewer imports used explicit packet hashes and individual
rationales; resume commands used `--as qualification-agent`. Development mode and
`PORTCO_LLM_ENABLED=false` were set for the pinned application. The delegated reviewer itself is an
AI agent; disabling the optional application judge is not a claim that no AI was involved.

Two inspection-helper errors (string step instead of enum; `transaction` instead of `tx`) and an
incorrect generated-file path were corrected without modifying application code or bypassing gates.
PowerShell rendered native logging on stderr as an error record during the first resume, but persisted
state showed the certification gate; later subprocess captures returned actual zero exit codes.
No failed financial result was suppressed or retried into an apparent pass.

This evidence qualifies an automated review/publication exercise. It does not replace the unexecuted
[consented operator pilot](../../OPERATOR-PILOT.md), prove business savings or accept a live service.
