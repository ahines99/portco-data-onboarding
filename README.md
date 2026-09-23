# Portfolio Company Data Onboarding Agent

Onboards an unfamiliar portfolio company's data into a canonical private-equity data model:

1. Profiles the source without ever reading row values.
2. Infers entities, keys and joins, and maps columns to the ontology.
3. Routes anything uncertain to a human.
4. Generates a tested dbt project and semantic layer.
5. Reconciles every metric to the cent in a disposable sandbox.
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
   reviewer 'alice' recorded approval a132e212 (22 decisions, 1 override)
   generated dbt + semantic layer; sandbox build exit 0; 17/17 reconciliation checks exact to the cent
   certified (6232731a) and published v0001: active_customers, arr, billings, cogs, ebitda, gross_margin_pct, mrr, opex, revenue_recognized
   audit log: 43 events, hash chain intact

== 2. Controlled failure path: malformed invoice lines + an injected source timeout
   injected timeout during profiling -> retried (attempts: 2), run continued to 'mapping_review'
   sandbox tests failed: non_negative_stg_billing__invoice_lines_amount, non_negative_stg_billing__invoice_lines_quantity
   run stopped at 'test_failures' - nothing is published unless a reviewer waives or the mapping changes
```

## Why this is not just a chatbot

| A chatbot would… | This system… |
|---|---|
| Keep state in the conversation | Persists every run, step attempt, output, evidence record, finding, approval and audit event in a database. Runs pause, resume, retry and rerun idempotently, and the same inputs give byte-identical outputs. |
| Read your data to "understand" it | Never sees a row. The source adapter only returns aggregates (counts, ratios, pattern-match counts computed in SQL). A PII guard blocks any MCP response containing PII-shaped data, and planted canary values are proven never to leak. |
| Do arithmetic in the prompt | Computes every number in code. Generated dbt marts are reconciled against independent Python reference calculators at zero tolerance, and against the fixture generator's own bookkeeping in golden tests. |
| Guess when unsure | Routes low-confidence, metric-bearing, PII, conflicting, unit-mismatched and "looks like revenue but isn't" mappings to review. Metrics without evidence are `NEEDS_EVIDENCE`, never estimated. |
| Let you type "approved" | Accepts approvals only from reviewer principals, never from the agent, and never from whoever started the run. Each approval is bound to a hash of exactly what was reviewed, and any later change revokes it. Publishing without a valid certification fails closed. |
| Follow instructions it reads | Treats source text as untrusted data. Instruction-like comments and values are flagged and withheld, and cannot change workflow state (eval case G15). |
| Be judged by vibes | Is gated in CI by 34 golden evaluation cases scored on the handoff's seven dimensions, plus about 250 tests, including a security suite and failure injection. |

## Quickstart

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). No Docker and no API keys are needed for
the demo, the tests or the evals.

```bash
uv sync --all-extras          # environment from uv.lock
uv run poe fixtures           # generate synthetic fixture databases into var/fixtures
uv run poe demo               # happy path + controlled failure path (~20 s)
uv run poe test               # full test suite (~2.5 min; dbt runs in sandboxes)
uv run poe eval               # 34 golden cases, gating report in evals/reports/latest.md
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
HTTP, run `uvicorn src.mcp_server:app` with `PORTCO_HTTP_TOKENS` set; each bearer token carries a
role and a tenant scope.

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
  naming), and 9 adversarial or fault variants, each with committed ground truth.
- **Generated dbt:** staging (rename, cast, reviewed transforms, PII hashed or dropped, filtered rows
  flagged), intermediate (cross-entity scoping), marts, MetricFlow semantic models and metrics.

Details: [docs/architecture.md](docs/architecture.md) · decisions: [docs/adr/](docs/adr/) ·
contracts: [docs/data_contracts.md](docs/data_contracts.md) · threats:
[docs/threat_model.md](docs/threat_model.md) · roadmap: [docs/ROADMAP.md](docs/ROADMAP.md) ·
acceptance audit: [docs/acceptance.md](docs/acceptance.md)

## Results (at time of writing)

| Measure | Result |
|---|---|
| Golden eval cases | 34/34 passing; every dimension at 100% |
| Mapping top-1 accuracy | 1.00 on fixture A (68 columns); fixture B (SAP naming) 34/35 exact, with the extra one flagged for review |
| Joins | 8/8 on fixture A and 4/4 on fixture B, no false positives; orphan rates exact |
| Metric reconciliation | Billings, ARR, active customers and GL revenue exact to the cent against two independent references |
| PII | 10/10 fixture A PII columns classified; zero canary leaks across outputs, artifacts, audit, evidence and published bundles |

## Limitations and v0.2

- Sources are DuckDB fixtures. Snowflake, Airbyte and catalog publishing are designed as further
  capability modules behind the same adapter and policy interfaces.
- Publish target is a versioned local directory; warehouse deployment needs environment-scoped approvals.
- The optional LLM mapping judge (`PORTCO_LLM_ENABLED=true`) is off by default. It can only reorder
  deterministic candidates or abstain, and it stays opt-in until a recorded live comparison beats the
  deterministic baseline ([ADR-0010](docs/adr/0010-llm-mapping-judge.md)).
- HTTP auth uses static dev bearer tokens; production needs an OAuth/JWT verifier.
- Postgres-specific tests run in CI (service container), not in the default local suite.

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
