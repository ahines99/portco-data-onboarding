# Portfolio Company Data Onboarding Agent

[![CI](https://github.com/ahines99/portco-data-onboarding/actions/workflows/ci.yml/badge.svg)](https://github.com/ahines99/portco-data-onboarding/actions/workflows/ci.yml)

**[Project page and recorded scripted replay](https://ahines99.github.io/portco-data-onboarding/)** ·
[Case study](docs/portfolio_case_study.md) · [Sample reports](docs/evidence/README.md) ·
[Release status](docs/RELEASE-STATUS.md)

Synthetic-data portfolio prototype by Alex Hines, developed with substantial AI assistance.
The recorded fixture demo uses automated reviewer decisions. [Six real model sessions](docs/evidence/live-study/README.md)
and a [captioned synthetic-voice tour](https://github.com/ahines99/portco-data-onboarding/releases/download/v0.1.0/portco-narrated-demo.mp4)
are available. Personal review and human annotations remain explicit [handoffs](docs/HUMAN-HANDOFF.md).

Onboards an unfamiliar portfolio company's data into a canonical private-equity data model:

1. Profiles the source through aggregates and explicitly approved category domains.
2. Infers entities, keys and joins, and maps columns to the ontology.
3. Routes anything uncertain to a human.
4. Generates a tested dbt project and semantic layer.
5. Executes every generated metric in a disposable sandbox and reconciles monetary amounts to the cent.
6. Publishes only what a human reviewer certified.

It is exposed to agents (for example Claude Code) through a typed MCP server and a set of Agent
Skills. The agent does the discovery; deterministic code does every calculation; humans hold every
approval.

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
| Be judged by vibes | Has CI gates for 37 golden evaluation cases across seven dimensions, plus 459 non-Postgres tests and four PostgreSQL tests, including security and failure injection. See the dated release evidence for exact scope. |

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
HTTP, run `uvicorn src.mcp_server:app` with `PORTCO_HTTP_TOKENS` set (the app refuses to start
without it); each bearer token carries a role and an explicit tenant scope
(`token=principal:role:company1|company2`, `*` for all). `GET /healthz` is the unauthenticated
liveness probe.

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

## Results (at time of writing)

| Measure | Result |
|---|---|
| Golden eval cases | 37/37 passing; every dimension at 100% |
| Mapping top-1 accuracy | 1.00 on fixture A (68 columns); fixture B (SAP naming) 34/35 exact, with the extra one flagged for review |
| Joins | 8/8 on fixture A and 4/4 on fixture B, no false positives; orphan rates exact |
| Metric reconciliation | All nine generated metric definitions executed and reconciled; monetary amounts exact to the cent; 26/26 demo checks including structural and mart checks |
| PII | 10/10 fixture A PII columns classified; zero canary leaks across outputs, artifacts, audit, evidence and published bundles |

## Limitations and v0.2

- Sources are DuckDB fixtures. Snowflake, Airbyte and catalog publishing are designed as further
  capability modules behind the same adapter and policy interfaces.
- Publish target is a versioned local directory; warehouse deployment needs environment-scoped approvals.
- The optional LLM mapping judge (`PORTCO_LLM_ENABLED=true`) is off by default. It can only reorder
  deterministic candidates or abstain, and it stays opt-in until a recorded live comparison beats the
  deterministic baseline ([ADR-0010](docs/adr/0010-llm-mapping-judge.md)).
- HTTP auth uses static dev bearer tokens; production needs an OAuth/JWT verifier.
- Postgres-specific tests are separate from the default local suite. Four tests passed against an
  isolated PostgreSQL 14.24 instance locally and PostgreSQL 16 in hosted CI on 2026-09-27.
- Hosted CI passed minimal wheel/sdist checks on Linux and Windows, and actual Docker tests for
  migrations, auth, certified publication, file hashes, audit integrity, MCP restart and full stack
  recreation with both named volumes preserved. Local Docker is unavailable; the CI run is the proof.
- An additional unfamiliar-schema probe is reported in full, including missed predictions, in
  [heldout-probe.json](docs/evidence/heldout-probe.json). Fixture accuracy is not real-world accuracy.
- MetricFlow 0.15.0 configuration validation failed in the isolated compatibility experiment;
  the supported local semantic executor is not a claim of full MetricFlow runtime compatibility.
- A recorded Claude Code session and the live with-vs-without-Skill comparison are still to do
  (they need a model session); the static Skill checks run in the test suite. The
  [three-prompt comparison harness](docs/skill_comparison.md) records and scores real transcripts
  once collected; it does not substitute synthetic results for live evidence.

## Project layout

```text
src/domain/        contracts, ontology loader, metric reference calculators, policies, PII guard
src/adapters/      DuckDB read-only adapter + SQL guard, repositories, artifact store, fault injection
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
