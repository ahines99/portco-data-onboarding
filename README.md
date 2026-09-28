# Portfolio Company Data Onboarding Agent

Hosting decision: **keep the portfolio free**, using GitHub Pages and the reproducible local workflow.
The live backend is not deployed. The [Render + Auth0 recipe](docs/LIVE-DEPLOYMENT.md) is an optional
paid deployment path; no recurring charges are authorized.

[![CI](https://github.com/ahines99/portco-data-onboarding/actions/workflows/ci.yml/badge.svg)](https://github.com/ahines99/portco-data-onboarding/actions/workflows/ci.yml)

**[Project page and recorded scripted replay](https://ahines99.github.io/portco-data-onboarding/)** ·
[Case study](docs/portfolio_case_study.md) · [Sample reports](docs/evidence/README.md) ·
[Release status](docs/RELEASE-STATUS.md)

Synthetic-data portfolio prototype by Alex Hines, developed with substantial AI assistance.
The recorded fixture demo uses automated reviewer decisions. [Six real model sessions](docs/evidence/live-study/README.md)
and a [captioned synthetic-voice tour](https://github.com/ahines99/portco-data-onboarding/releases/download/v0.1.0/portco-narrated-demo.mp4)
are available. Alex approved finalization; [final acceptance](docs/FINAL-ACCEPTANCE.md) records delegated
workflow completion, accepted annotations and known scope limits for that historical release.
Render/Auth0 account access and the real agent-token preflight are verified. Paid deployment was
declined; live reviewer, hosting and recovery acceptance remain unverified.

Demonstrates governed onboarding of supported synthetic SaaS and SAP-style sources into a canonical
private-equity data model:

1. Profiles the source through aggregates and explicitly approved category domains.
2. Infers entities, keys and joins, and maps columns to the ontology.
3. Routes uncertain mapping proposals to a reviewer.
4. Generates a tested dbt project and semantic layer.
5. Executes every generated metric in a disposable sandbox and reconciles monetary amounts to the cent.
6. Publishes only the exact bundle certified by a separate reviewer principal.

It is exposed to agents (for example Claude Code) through a typed MCP server and a set of Agent
Skills. The agent assists discovery; deterministic code performs authoritative calculations; separate
reviewer principals hold approval authority. Demo reviewers are automated test identities; the
accepted portfolio run used explicitly delegated owner authorization.

The original unfamiliar-schema probe produced **zero proposals and 0/10 target matches**;
it was never approved or published. That [historical evidence](docs/evidence/heldout-probe.json)
remains unchanged. Current development adds reviewed structural inference and a separate-agent
[frozen benchmark](evals/unfamiliar/README.md). Its [first post-change run](docs/evidence/unfamiliar-benchmark-first-postchange.json)
matched 31/33 proposals (31/32 labeled targets), unchanged from the reconstructed baseline,
and **failed the safety gate** because a competing monetary interpretation bypassed review.
The [post-benchmark remediation](docs/evidence/unfamiliar-benchmark.json) passes safety with 32/33
correct proposals and 32/32 positive targets covered. Review increases to 7/33; one wrong reviewed
proposal and eight unresolved opaque fields remain. This is remediation after feedback, not fresh
held-out validation or arbitrary-schema accuracy.

An operator can now ingest [typed CSV extracts](docs/CSV-SOURCE.md). A [synthetic CSV smoke run](docs/evidence/csv-source-smoke.json)
imported 11 tables / 14,639 rows, crossed service restarts and published nine metrics with a separate
automated reviewer. A bounded public-data exercise imported
and profiled [10,000 real historical retail rows](docs/PUBLIC-OPERATING-DATA.md), with six passing
aggregate controls. This proves ingestion/profiling, not financial certification or customer impact.
See the [operator pilot protocol](docs/OPERATOR-PILOT.md) and [resume/claims guide](docs/RESUME-AND-CLAIMS.md).

```text
uv sync --all-extras && uv run poe demo
```

```text
== 1. Success path: fixture A (synthetic B2B SaaS company)
   agent profiled, inferred entities/joins and proposed mappings -> paused at 'mapping_review' with 22 review items
   trap caught -> billing.invoice_lines.amount -> invoice_line.amount (suggest cents_to_major) [UNIT_MISMATCH]
   trap caught -> crm.opportunities.rev -> opportunity.amount [LOW_CONFIDENCE, SEMANTIC_TRAP]
   agent tried to approve its own proposals -> Forbidden
   reviewer 'alice' recorded approval a132e212 (22 decisions)
   generated dbt + semantic layer; sandbox build exit 0; 26/26 reconciliation checks passed (money exact to the cent)
   certified (6232731a) and published v0001: active_customers, arr, billings, cogs, ebitda, gross_margin_pct, mrr, opex, revenue_recognized
   audit log: 46 events, hash chain intact

== 2. Controlled failure path: malformed invoice lines + an injected source timeout
   injected timeout during profiling -> retried (attempts: 2), run continued to 'mapping_review'
   sandbox tests failed: non_negative_stg_billing__invoice_lines_amount, non_negative_stg_billing__invoice_lines_quantity
   run stopped at 'test_failures' - nothing is published unless a reviewer waives or the mapping changes

== 3. Prompt injection: instructions planted in a source table comment
   1 comment(s) flagged as untrusted; they are quoted as data, never followed
   mappings identical to the clean run: yes (68 columns)
   planted text in any artifact or finding: NONE
```

## Why this is not just a chatbot

| A chatbot would… | This system… |
|---|---|
| Keep state in the conversation | Persists every run, step attempt, output, evidence record, finding, approval and audit event in a database. Runs pause, resume, retry and rerun idempotently under an execution lease, and the same inputs give identical content hashes. |
| Read your data to "understand" it | The profiling adapter returns aggregates (counts, ratios, pattern-match counts computed in SQL). Category labels require an operator-approved domain for the exact column; undeclared or unexpected values are withheld ([ADR-0003](docs/adr/0003-aggregate-only-adapter.md)). A PII guard scans MCP responses, and the fixture tests check planted canaries across output surfaces. |
| Do arithmetic in the prompt | Computes every number in code. Generated dbt marts are reconciled against independent Python reference calculators at zero tolerance, and against the fixture generator's own bookkeeping in golden tests. |
| Guess when unsure | Routes low-confidence, metric-bearing, PII, conflicting, unit-mismatched and "looks like revenue but isn't" mappings to review. Metrics without evidence are `NEEDS_EVIDENCE`, never estimated. |
| Let you type "approved" | Accepts approvals only from reviewer principals, never from the agent, and never from whoever started the run. Each approval is bound to a hash of exactly what was reviewed, and any later change revokes it. Publishing without a valid certification fails closed. |
| Follow instructions it reads | Treats source text as untrusted data. Instruction-like comments and values are flagged and withheld, and cannot change workflow state (eval case G15). |
| Be judged by vibes | Has golden evaluation gates across seven dimensions plus general, security, PostgreSQL, packaging and container checks. See the [release evidence](docs/RELEASE-STATUS.md) for dated results; test populations overlap. |

## Quickstart

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). No Docker and no API keys are needed for
the demo, the tests or the evals.

If uv is installed as a Python module but is not on PATH, replace `uv` below with `python -m uv`.

```bash
uv sync --all-extras          # environment from uv.lock
uv run poe fixtures           # generate synthetic fixture databases into var/fixtures
uv run poe demo               # happy path, controlled failure path, prompt injection (~25 s)
uv run poe test               # full test suite (~3 min; dbt runs in sandboxes)
uv run poe eval               # 37 golden cases; report in evals/reports/latest.md (--snapshot for a dated copy)
uv run poe cov-metrics        # metric reference calculators at 100% branch coverage
uv run poe lint && uv run poe typecheck
```

### Drive it by hand (CLI)

```bash
uv run portco run --fixture portco_a                      # agent: runs until the first gate
uv run portco review <run_id> --export review.yaml        # human: see what needs deciding
uv run portco review <run_id> --import review.yaml --reviewer alice --default approve
uv run portco resume <run_id>                             # agent: generate, sandbox-test, stop for certification
uv run portco review <run_id> --export cert.yaml && uv run portco review <run_id> --import cert.yaml --reviewer alice --default approve
uv run portco resume <run_id>                             # publish
uv run portco report <run_id> --out report.md             # run report / certification packet
uv run portco audit <run_id> --verify                     # hash-chain check
```

### Use it from Claude Code (MCP + Skills)

`.mcp.json` registers the stdio server (`uv run portco-mcp`) as an **agent** principal. Copy
`skills/*` into `.claude/skills/`. See [docs/agent_walkthrough.md](docs/agent_walkthrough.md). Over
HTTP in development, run `uvicorn src.mcp_server:app` with `PORTCO_HTTP_TOKENS` set; each
static token carries a role and tenant scope (`token=principal:role:company1|company2`, `*` for all).
Production mode requires the [JWT deployment configuration](docs/LIVE-DEPLOYMENT.md), with
signature, issuer, audience, lifetime, role and explicit company claims validated. `GET /healthz`
is liveness; `GET /readyz` checks migration and writable storage readiness. Real hosted identity
integration remains unverified.

## MCP surface

| Kind | Name | Notes |
|---|---|---|
| Tools | `start_onboarding_run`, `get_run_status`, `resume_run`, `list_pending_reviews`, `profile_schema`, `propose_canonical_mapping`, `generate_dbt_artifacts`, `run_sandbox_tests`, `publish_run`, `healthcheck` | Agent-callable; typed inputs and outputs; typed error contract |
| Tools (human) | `submit_mapping_review`, `certify_run` | Reviewer principals only |
| Resources | `project://policies`, `ontology://pe/v1`, `ontology://pe/v1/metrics/{metric}`, `run://{run_id}/{summary,profile,entities,joins,mapping,resolved-mapping,test-report,certification-packet,findings,audit,metrics}`, `run://{run_id}/artifacts/{+path}`, `evidence://{evidence_id}`, `finding://{finding_id}/lineage` | Tenant-scoped; path traversal rejected |
| Prompts | `onboarding_kickoff`, `review_run`, `explain_mapping` | Reference resources by URI; never embed data |

## How it works

```text
connection_validation → schema_profiling → entity_inference → join_inference → canonical_mapping
   → [Gate A: mapping_review] → artifact_generation → automated_tests (sandbox) → [test_failures waiver?]
   → [Gate B: human_certification] → publish
```

- **Ontology as data:** `ontology/pe_canonical_v1.yaml` defines 15 entities, synonyms, relationships
  and 18 metrics with PE pitfalls. Scoring weights live in `ontology/scoring.yaml`.
- **Fixtures with answer keys:** fixture A (SaaS with planted traps), fixture B (SAP-style
  naming), and 10 adversarial or fault variants, each with committed ground truth.
- **Generated dbt:** staging (rename, cast, reviewed transforms, PII hashed or dropped, filtered rows
  flagged), intermediate (cross-entity scoping), marts, MetricFlow semantic models and metrics.

Details: [docs/architecture.md](docs/architecture.md) · decisions: [docs/adr/](docs/adr/) ·
contracts: [docs/data_contracts.md](docs/data_contracts.md) · threats:
[docs/threat_model.md](docs/threat_model.md) · roadmap: [docs/ROADMAP.md](docs/ROADMAP.md) ·
acceptance audit: [docs/acceptance.md](docs/acceptance.md) ·
portfolio finalization: [docs/PORTFOLIO-ROADMAP.md](docs/PORTFOLIO-ROADMAP.md) ·
September audit and fixes: [docs/REMEDIATION-2026-09-27.md](docs/REMEDIATION-2026-09-27.md)

Setup, tokens, upgrades and recovery: [operations](docs/operations.md).

## Historical supported-fixture results

These are recorded portfolio-fixture results, not measurements of arbitrary CSV inputs.
Use [release status](docs/RELEASE-STATUS.md) for code/release-specific verification.

| Measure | Result |
|---|---|
| Golden eval cases | 37/37 passing; every dimension at 100% |
| Mapping top-1 accuracy | 1.00 on fixture A (68 columns); fixture B (SAP naming) 34/35 exact, with the extra one flagged for review |
| Joins | 8/8 on fixture A and 4/4 on fixture B, no false positives; orphan rates exact |
| Metric reconciliation | All nine generated metric definitions executed and reconciled; monetary amounts exact to the cent; 26/26 demo checks including structural and mart checks |
| PII | 10/10 fixture A PII columns classified; zero canary leaks across outputs, artifacts, audit, evidence and published bundles |

## Current scope and limitations

- Sources include generated DuckDB fixtures and operator-imported, typed CSV snapshots. The
  CSV boundary is tested independently of the fixture registry; it is not a live Snowflake,
  Salesforce, SAP, SFTP or warehouse connector. The public retail exercise stops at profiling.
- Publish target is a versioned local directory; warehouse deployment needs environment-scoped approvals.
- The optional LLM mapping judge (`PORTCO_LLM_ENABLED=true`) is off by default. It can only reorder
  deterministic candidates or abstain, and it stays opt-in until a recorded live comparison beats the
  deterministic baseline ([ADR-0010](docs/adr/0010-llm-mapping-judge.md)).
- HTTP supports static development tokens and production JWT verification. Real Auth0/Render
  acceptance, hosted persistence/recovery and runtime risk decisions remain pending.
- PostgreSQL tests run separately from the default local suite. Do not add local and hosted test
  counts together; use the exact release CI and verification assets for the current population.
- Hosted CI passed minimal wheel/sdist checks on Linux and Windows, and actual Docker tests for
  migrations, auth, certified publication, file hashes, audit integrity, MCP restart and full stack
  recreation with both named volumes preserved. Local Docker is unavailable; the CI run is the proof.
- The unfamiliar-schema probe produced zero proposals and matched 0/10 labeled targets; its
  [full report](docs/evidence/heldout-probe.json) preserves every missed prediction. Fixture accuracy
  is not real-world accuracy.
- MetricFlow 0.15.0 configuration validation failed in the isolated compatibility experiment;
  the supported local semantic executor is not a claim of full MetricFlow runtime compatibility.
- [Six real Claude Code sessions](docs/evidence/live-study/README.md) completed the three-prompt
  comparison. Owner-approved assistant annotations count three findings in each condition; only
  one session invoked a Skill body. The review is non-exhaustive and not independent blinded coding,
  and no general Skill improvement is established. The [scorer](docs/skill_comparison.md) preserves
  those provenance qualifications when regenerating the report.

## Project layout

```text
src/domain/        contracts, ontology loader, metric reference calculators, policies, PII guard
src/adapters/      DuckDB adapter + SQL guard, typed CSV snapshots, repositories, artifact store
src/services/      one module per workflow step, approvals, optional LLM judge
src/workflows/     persistent engine, step wiring, facade used by CLI and MCP
src/capabilities/  MCP tools, resources, prompts, PII-guard middleware, auth
skills/            Agent Skills (SKILL.md + references/)
ontology/          canonical PE ontology, abbreviations, scoring weights
templates/dbt/     dbt project templates and generic tests
fixtures/          committed ground truth for generated fixtures
evals/             golden cases, drivers, checks, reports
tests/             unit, integration, golden, security, MCP, snapshot tests
```
