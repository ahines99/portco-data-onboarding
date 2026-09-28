# Resume framing and evidence-backed claims

This is a governed data-engineering and applied-AI portfolio project developed with substantial
AI assistance. The strongest story is explicit business definitions, deterministic reconciliation,
separate reviewer authority and recovery across database/filesystem failures. Completed synthetic
workflows, a bounded real-data ingestion exercise and a deployment candidate have different scopes.
See [current release status](RELEASE-STATUS.md) before quoting version-specific test counts.

The current [automated qualification release](AUTOMATED-QUALIFICATION.md) follows the owner's
instruction to make execution agentic or automated. Separate operator/reviewer agents completed a
synthetic workflow on pinned baseline `03c4fb3`; actual PostgreSQL acceptance subsequently passed
on `25c6937` in [hosted CI](https://github.com/ahines99/portco-data-onboarding/actions/runs/36443092813).
Use the [v0.2.0-rc.3 record](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.2.0-rc.3)
and [release status](RELEASE-STATUS.md) for integrated verification and exact release provenance. The project remains free-only: static portfolio and local execution,
with no deployed production backend. Automated qualification does not become a human pilot.

## Recommended resume entry

**Portfolio Company Data Onboarding Agent - AI-Assisted Data Engineering Project**

Python, SQL, dbt, DuckDB, PostgreSQL, MCP, Docker, GitHub Actions

- Directed an AI-assisted project for governed onboarding of supported company schemas, with
  evidence-linked canonical mappings, generated dbt models and separate review/certification gates.
- Delivered deterministic reconciliation of nine financial metrics in synthetic workflows, persistent
  execution state, content-bound approvals and recoverable versioned publication.
- Extended ingestion to typed CSV snapshots and validated ingestion/profiling on 10,000 public
  historical retail rows; maintained reproducible evaluation, packaging and security checks.

Optional connector bullet, when relevant to the role:

- Added a bounded read-only PostgreSQL snapshot connector and verified extraction of 11 synthetic
  tables / 14,639 rows through nine-metric reconciliation and certified publication in actual
  PostgreSQL CI, with schema/privilege checks and atomic registration.

This is verified synthetic integration, not a production deployment or customer-source claim.

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
| PostgreSQL source connector | [Connector contract](POSTGRES-SOURCE.md), [actual PostgreSQL CI](https://github.com/ahines99/portco-data-onboarding/actions/runs/36443092813) | 11 synthetic tables / 14,639 rows through nine-metric publication; 58 generated-file hashes, 59 published files, 45 audit events, zero waivers; no customer credentials or continuous synchronization |
| Separate-agent operated/reviewed workflow | [Operator record](evidence/agent-operator-qualification/README.md), [reviewer verification](evidence/agent-reviewer-qualification/README.md) | Pinned baseline `03c4fb3`: six supported metrics, 38 verified publication files, 46 audit events; source-informed automated review, not human or blinded validation |
| Real historical operating data | [Public retail exercise](PUBLIC-OPERATING-DATA.md), [aggregate evidence](evidence/public-retail-profile.json) | 10,000 source-order rows imported/profiled; six extract/profile controls, no approved mapping, certified metrics or customer participation |
| Unfamiliar-schema evaluation | [Frozen benchmark](../evals/unfamiliar/README.md) and its immutable reports | Cases authored by a separate agent before mapper changes; not external human validation or fully blinded research |
| Six-case agent qualification v2 | [Frozen v2 corpus and reports](../evals/agent_qualification_v2/README.md) | First safety failure retained; post-feedback repair changes review coverage, not mapping accuracy; separate-agent authorship is not external human evaluation |
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
Those 7/33 review counts belong to the preserved historical report. With the later entity-uncertainty
repair, the [current v1 regression](evidence/unfamiliar-benchmark-rc3.json) still passes safety at 32/33 correct proposals and 32/32 targets,
but requires review for 17/33 proposals; eight fields remain unresolved.

The new six-case [v2 corpus](../evals/agent_qualification_v2/README.md) is a separate experiment.
Its first run made 42/52 correct proposals, covered 42/43 positive targets and failed safety.
Remediation leaves those accuracy counts unchanged, routes 48/52 proposals to review and passes
safety. Ten wrong proposals and ten unresolved fields remain. This records a safer review boundary,
not improved mapping accuracy or untouched held-out success.

A later passing benchmark cannot erase an earlier failure. A source-import exercise cannot establish
mapping correctness. A passing test cannot establish a real human's consent, review or usability.
Keep these evidence boundaries when shortening the project description.

## Suggested interview introduction

"I directed an AI-assisted project exploring how portfolio-company onboarding can remain auditable
when schema names, units and business definitions disagree. The system profiles sources, proposes
mappings, generates dbt models and reconciles financial metrics, with separate review and certification.
I extended the boundary to typed CSV extracts and exercised ingestion on public historical retail
data. The strongest engineering work is keeping calculations, permissions and recovery explicit.
Separate automated operator and reviewer agents completed a supported baseline workflow.
The PostgreSQL connector passed actual database-to-publication acceptance using synthetic data.
Human impact and live production operations remain unverified."

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

The owner selected automated qualification instead of recruiting human participants for the active
roadmap. The human pilot kit remains unexecuted and optional future evidence; do not imply the
agent exercise satisfied its consent or impact gates. Free-only operation remains in force.

Until those records exist, describe stronger external claims as unverified future work. Never fill missing outcomes
with recommended numbers, projected savings or inferred approval.
