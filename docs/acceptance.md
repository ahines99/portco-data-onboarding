# Acceptance audit (POD-907)

Audit of the handoff's acceptance checklist against the implementation, as of 2026-09-23. "Proven by"
lists the tests (`tests/…`) and golden eval cases (`G..`, `evals/cases.yaml`) that fail if the
property breaks.

| # | Acceptance item | Status | Proven by |
|---|---|---|---|
| 1 | Connection validation has a deterministic artifact, audit event, and failure path | ✅ | `ConnectionCheck` artifact; `connection_checked` audit; G19 (outage, retry, resume), `test_write_capable_connection_is_refused`, `test_every_step_has_an_audited_failure_path[connection_validation]` |
| 2 | Schema profiling … | ✅ | `SchemaProfile` + per-table evidence; `schema_profiled`; G18 (timeout retried), G20/G21, `test_every_step_has_an_audited_failure_path[schema_profiling]` |
| 3 | Entity inference … | ✅ | `EntityInference` with feature breakdowns; `entities_inferred`; G03, G12, `test_internal_crash_is_contained_without_leaking_details`, parametrized failure test |
| 4 | Join inference … | ✅ | `JoinGraph` with containment evidence; `joins_inferred`; G04, G13, parametrized failure test |
| 5 | Canonical mapping … | ✅ | `MappingSet` + review items; `mapping_proposed`; G05, G06, G10, G11, G14, G32, parametrized failure test |
| 6 | Artifact generation … | ✅ | `ArtifactBundle` (manifest hash, deterministic, snapshot-tested); `artifacts_generated`; `test_generation_fails_closed_when_mapping_approval_is_revoked` |
| 7 | Automated tests … | ✅ | `TestReport` (dbt results + exact reconciliation); `sandbox_passed`/`sandbox_failed`; G08, G09, G20, G28 |
| 8 | Human certification … | ✅ | `CertificationPacket`; `certification_requested`/`certified`; G24 (stale certification revoked), `test_rejected_certification_fails_the_run` |
| 9 | Publish … | ✅ | `PublishReceipt` + `certification.json`; `publish_completed`/`policy_denied`; G22, G25 (idempotent), `test_publish_without_certification_is_denied_and_audited` |
| 10 | Every material recommendation includes evidence or says evidence is insufficient | ✅ | `Finding` validator rejects SUPPORTED findings without evidence; eval `evidence_fidelity` (every finding resolves to stored evidence or is `NEEDS_EVIDENCE`); lineage resource |
| 11 | All irreversible actions are disabled or human-approved | ✅ | Publish is the only side effect; it needs a hash-bound certification (ADR-0004); G22, G23, G24 |
| 12 | MCP tools have typed schemas and integration tests | ✅ | `tests/test_mcp.py` (in-process, stdio and authenticated HTTP); G31 tool trace |
| 13 | At least one Skill is dynamically useful and not just duplicate prompt text | ✅ static / ⚠️ live | `tests/test_skills.py` checks tool, resource and prompt references against the live server, rejects near-duplicates, and requires references to exist. The live with-vs-without-Skill comparison needs a model session and has not been run ([docs/agent_walkthrough.md](agent_walkthrough.md) §4) |
| 14 | All arithmetic/financial/statistical calculations have deterministic tests | ✅ | `tests/test_metrics_reference.py` (hand-computed micro-fixtures, including edge cases); reference equals independent ground truth; G08/G09 |
| 15 | The demo can survive one injected tool failure | ✅ | `poe demo` failure path (injected timeout retried); G18, G19 |

## Handoff "Add tests for" list

| Item | Proven by |
|---|---|
| each project-specific MCP tool | `tests/test_mcp.py` |
| authorization / approval rejection | G22, G23, G30; `test_agent_cannot_approve_and_denial_is_audited`, forged approval ids |
| workflow pause/resume | G26; `test_resume_after_gate_a_continues_at_generation_without_rerunning_steps` |
| idempotent reruns | G25; `test_idempotent_rerun_reuses_steps_and_produces_identical_hashes` |
| provenance links | `test_resources_and_templates` (lineage), `test_finding_citing_unknown_evidence_is_rejected_by_engine_rules` |
| deterministic calculation fixtures | `tests/test_metrics_reference.py` |
| at least one injected dependency failure | G18, G19; `test_transient_timeout_is_retried`, `test_persistent_outage_fails_controlled_then_resumes` |

## Definition of done (handoff)

| Requirement | Status |
|---|---|
| Typed MCP capabilities | ✅ 12 tools, 16 resources/templates, 3 prompts |
| Persisted workflow state | ✅ SQLAlchemy + Alembic; SQLite locally, Postgres in CI |
| Evidence and provenance preserved | ✅ Deterministic evidence ids, lineage resource, hash-chained audit |
| Stops at approval boundaries | ✅ Three gates, hash-bound approvals, separation of duties |
| At least one Agent Skill | ✅ Five, linted against the live server |
| Integration tests | ✅ About 250 tests plus 34 gating eval cases |
| End-to-end demo with success and controlled failure paths | ✅ `poe demo` |

## Known gaps (tracked for v0.2)

- Live with-vs-without-Skill and LLM-judge comparisons need model credentials; the tooling is in place
  (`evals/judge_eval.py --mode record`).
- The Postgres suite (`tests/test_postgres.py`) runs in the CI service container; it was not run in the
  local build environment, which has no Docker.
- The `mf validate-configs` MetricFlow CLI check is not installed; semantic manifests are validated by
  `dbt parse`/`build` instead.
- The OpenTelemetry OTLP exporter is optional; spans are verified with the in-memory exporter.
