# Resume framing and evidence-backed claims

This is a governed data-engineering and applied-AI portfolio project developed with substantial
AI assistance. The strongest story is explicit business definitions, deterministic reconciliation,
separate reviewer authority and recovery across database/filesystem failures. Completed synthetic
workflows, a bounded real-data ingestion exercise and a deployment candidate have different scopes.
See [current release status](RELEASE-STATUS.md) before quoting version-specific test counts.

## Recommended resume entry

**Portfolio Company Data Onboarding Agent - AI-Assisted Data Engineering Project**

Python, SQL, dbt, DuckDB, PostgreSQL, MCP, Docker, GitHub Actions

- Directed an AI-assisted project for governed onboarding of supported company schemas, with
  evidence-linked canonical mappings, generated dbt models and separate review/certification gates.
- Delivered deterministic reconciliation of nine financial metrics in synthetic workflows, persistent
  execution state, content-bound approvals and recoverable versioned publication.
- Extended ingestion to typed CSV snapshots and validated ingestion/profiling on 10,000 public
  historical retail rows; maintained reproducible evaluation, packaging and security checks.

"Directed" matches the recorded project role. Use "personally implemented" for a component only if
that is accurate and you can explain your contribution. Owner approval of a result does not mean the
owner manually authored or reviewed every line. The [accepted personal statement](ASSISTED-ACCEPTANCE.md)
and [final acceptance](FINAL-ACCEPTANCE.md) retain the distinction between AI assistance and delegation.

For backend roles, emphasize prepared/complete publication states, hash binding, retries and
concurrency. For data roles, emphasize declared units, joins, row retention, dbt and reconciliation.
For applied-AI roles, emphasize typed MCP boundaries, uncertainty, separate reviewer authority and
honest evaluation. Do not add all technologies and counts to every bullet.

## Claims matrix

| Claim | Evidence | Allowed scope / boundary |
|---|---|---|
| Governed end-to-end onboarding | [Accepted synthetic run](evidence/owner-acceptance/acceptance.json), [case study](portfolio_case_study.md) | Supported synthetic workflow through separate reviewer certification; recorded reviewers include automated/delegated identities |
| Nine reconciled financial metrics | [Reconciliation](evidence/reconciliation.json) | Generated supported-fixture metrics, not nine audited customer KPIs |
| Typed external extract ingestion | [CSV source contract](CSV-SOURCE.md), [synthetic full-workflow smoke](evidence/csv-source-smoke.json) | Operator-imported files, immutable registered snapshots; not direct Salesforce/SAP/Snowflake credentials or a live sync |
| Real historical operating data | [Public retail exercise](PUBLIC-OPERATING-DATA.md), [aggregate evidence](evidence/public-retail-profile.json) | 10,000 source-order rows imported/profiled; six extract/profile controls, no approved mapping, certified metrics or customer participation |
| Unfamiliar-schema evaluation | [Frozen benchmark](../evals/unfamiliar/README.md) and its immutable reports | Cases authored by a separate agent before mapper changes; not external human validation or fully blinded research |
| Historical generalization failure | [Original probe](evidence/heldout-probe.json) | Zero proposals, 0/10 matches; retain alongside later measurements rather than silently replacing it |
| Financial calculation coverage | Exact release CI coverage job | 100% statement/branch coverage of the metric reference module where verified, not whole-project coverage |
| Durable/recoverable publication | [Recovery decision](adr/0012-recoverable-publication.md), hosted container/PostgreSQL tests | Tested failure windows and persistence; not proven high availability or every hosting platform |
| Production JWT controls | [Deployment guide](LIVE-DEPLOYMENT.md) | Implemented and tested resource-server controls; actual tenant, hosting and recovery acceptance pending |
| Small real-agent study | [Six sessions](evidence/live-study/README.md) | Actual transcripts, owner-approved assistant annotations; no established Skill efficacy |
| Customer benefit / time savings | [Pilot protocol](OPERATOR-PILOT.md) only | Not measured; no adoption, ROI, analyst-hour savings or causal impact claim |
| Security review | [Current image assessment](image-risk-assessment.md) and exact scan assets | Specific controls and disclosed findings; no "vulnerability-free," certification or blanket production-safety claim |

The [first frozen post-change benchmark](evidence/unfamiliar-benchmark-first-postchange.json)
matched 31/33 proposals (31/32 targets), the same as the reconstructed baseline, and failed safety.
The [remediation rerun](evidence/unfamiliar-benchmark.json) passes safety with 32/33 correct
proposals and 32/32 targets covered, after feedback from the first run. Do not claim an independently
validated accuracy improvement. Review rises to 7/33; one wrong reviewed proposal and eight opaque
fields remain unresolved. This is post-benchmark remediation, not a new held-out study.

A later passing benchmark cannot erase an earlier failure. A source-import exercise cannot establish
mapping correctness. A passing test cannot establish a real human's consent, review or usability.
Keep these evidence boundaries when shortening the project description.

## Suggested interview introduction

"I directed an AI-assisted project exploring how portfolio-company onboarding can remain auditable
when schema names, units and business definitions disagree. The system profiles sources, proposes
mappings, generates dbt models and reconciles financial metrics, with separate review and certification.
I extended the boundary to typed CSV extracts and exercised ingestion on public historical retail
data. The strongest engineering work is keeping calculations, permissions and recovery explicit.
The live hosting and operator-impact pilot are still unverified."

Be ready to explain a cents-to-dollars transformation, a retained customer with no CRM match, the
stale-approval check, and a crash between publication rename and database commit. Explain why a
perfect fixture score or public-data import does not imply arbitrary-company accuracy.

## Evidence required before stronger wording

- **"Deployed live":** actual HTTPS endpoint, real identity roles and denial checks, restart persistence,
  accepted runtime risk controls and coordinated restore evidence, linked to the deployed commit.
- **"Reduced onboarding time":** consented paired operator measurements at a common output scope,
  setup/review effort and failures included, with sample size and design limitations disclosed.
- **"Used by a portfolio company":** actual participation, authorized identifying language and an
  accountable owner's approval to share; public historical data does not qualify.
- **"Generalizes to unfamiliar schemas":** broader fixed tasks authored independently, no answer-key
  leakage/tuning, uncertainty and incorrect-proposal reporting, and additional operating-source evidence.

Until those records exist, describe them as prepared or planned work. Never fill missing outcomes
with recommended numbers, projected savings or inferred approval.
