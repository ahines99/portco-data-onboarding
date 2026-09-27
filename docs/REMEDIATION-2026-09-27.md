# Audit remediation — 2026-09-27

The [five-agent repository audit](AUDIT-2026-09-27.md) identified 19 numbered findings plus
validation and delivery gaps. The authorized follow-up implemented all 19 fixes and the locally
executable validation work. Docker, hosted CI, MetricFlow CLI and live model comparisons remain
explicitly unverified; this record does not treat configured jobs or replay results as live evidence.

The repository contains a working fixture-backed onboarding application: a persistent nine-step
workflow, three human review boundaries, aggregate source profiling, deterministic mapping,
generated dbt and semantic definitions, financial reconciliation, certified local publication,
CLI and MCP interfaces, five agent Skills, and golden evaluation gates. It is not yet a production
warehouse connector or production identity system. The baseline audit inventories these components
and maps the remaining roadmap work.

## Implementation workstreams

Five distinct agents handled security, publication and persistence, evaluation, semantic execution,
and deployment/acceptance. They ran in waves within the runtime concurrency limit. The lead
integrated their changes, fixed packaging and runtime configuration, added a real local OTLP
export check, and reran the combined verification. All edits remain local and uncommitted; the
repository has no configured remote, and no hosted workflow or deployment was initiated.

## Finding disposition

| Finding | Implemented behavior | Regression evidence |
|---|---|---|
| F01 Schema authorization | Requested schemas can only narrow the registered allowlist; empty input preserves its restriction. | `tests/security/test_final_security.py` |
| F02 Approval overrides | Plain approve/reject cannot carry an override; resolution revalidates decisions. Override accounting records actual changes. | Security regressions; `tests/test_cli_and_observability.py` |
| F03 Publication recovery | Durable prepared/complete lifecycle reserves a version and recovers crashes without returning a receipt for missing output. Reuse verifies the exact file set and content. | `tests/test_publication_recovery.py`; PostgreSQL recovery test |
| F04 Concurrent audit appends | SQLite transactions acquire the write lock before reading the chain head; PostgreSQL retains row locking. | Concurrent audit tests on SQLite and PostgreSQL |
| F05 Metric certification | Publication reloads and validates the bundle and every metric's effective approval, including expiration, revocation and exclusions. | Publication recovery and certification regressions |
| F06 Read-only verification | Unique transactional probe accepts only the expected database read-only error; unrelated errors fail closed. | Security regressions |
| F07 Category privacy | Exact-column operator-approved domains replace name-shape heuristics as the disclosure boundary. Undeclared or unexpected categories are withheld. | Security regressions; ADR-0003 |
| F08 Example settings | The example step timeout is 900 seconds, exceeding the 600-second dbt timeout. | `tests/test_runtime_configuration.py` |
| F09 Wheel packaging | Runtime ontology, templates, migrations, fixture truth, demo reviews and lockfile ship as resources. Installed runs use writable runtime paths. | Clean installed-wheel smoke outside the checkout |
| F10 Publication cancellation | Finalization checks the execution owner, status, lease, deadline and cancellation under locks. Late cancellation is refused after the current publish step has finalized. | Publication cancellation, timeout and rerun regressions |
| F11 Sandbox cache | Full manifest, source, mapping, implementation and configuration identity is checked; a sidecar verifies the full digest behind shortened directory names. | `tests/test_semantic_execution.py` |
| F12 Step cache/resume | Hashes cover source implementation, ontology/templates, lockfile, semantic settings, judge identity and connection policy. Resume rechecks skipped steps, rewinds at the first mismatch and revokes affected approvals. | Runtime configuration tests; four resume/configuration regressions in `tests/test_engine_leases.py` |
| F13 Waiver binding | Waivers bind the substantive report, including reconciliation details; only volatile timing/cache data and the waiver decision itself are excluded. | Semantic/waiver regressions |
| F14 Empty eval passes | Unknown, empty and checkless selections fail; partial error reports cannot pass the gate. | `tests/test_eval_regressions.py` |
| F15 Judge decision rule | Saturated baselines allow equality; meaningful improvement is still required elsewhere. All populated confidence buckets and four held-out challenges are checked. Judge remains disabled by default. | Judge tests and replay comparison report |
| F16 Zero-denominator margin | Generated gross-margin expression uses `NULLIF`; zero revenue yields null rather than infinity. | Actual generated semantic execution tests |
| F17 Metric coverage | The local executor reads generated YAML and executes all nine supported monthly metric definitions, reconciling with independent source/reference calculations. Missing or unsupported definitions fail closed. | Semantic tests; G08/G09; demo 26/26 checks |
| F18 Eval cache decisions | Full normalized decisions, including reject and waive, participate in the case cache identity. | Eval cache regressions |
| F19 Compose exposure | Local Compose ports bind to loopback and no known fallback bearer tokens are supplied. A container smoke job uses an ephemeral token. | Configuration review; ASGI smoke-probe tests; actual Docker run still pending |

Additional changes verify blob hashes on read, reject publication path escapes and modified files,
report labeled mapping coverage and unknown proposals, check evidence payload integrity and claim
support, and verify publication files in the eval harness. PostgreSQL tests now cover a full
certified workflow, concurrency and recovery. The three-prompt Skill comparison harness accepts
real paired transcripts with model/settings and human-review metadata. Optional HTTP OTLP export
has a packaged dependency extra and a real local collector test.

## Final verification

Environment: Windows, Python 3.12.10, frozen dependencies; isolated PostgreSQL 14.24 under WSL.
The temporary PostgreSQL server was stopped after the final run.

| Check | Actual result |
|---|---|
| Full non-Postgres suite | **451 passed, 4 deselected**, 211.66 seconds; zero failures or skips |
| PostgreSQL suite | **4 passed, 451 deselected**, 11.86 seconds; migration parity, append-only audit, certified publication, concurrency and recovery |
| Golden eval | **37/37 cases and 72/72 dimension checks passed**, 118.5 seconds; [dated report](../evals/reports/2026-09-27.md) |
| Metric reference coverage | **16 tests passed; 100% statements and branches** (201 statements, 58 branches) |
| Ruff lint / format | Passed; 115 Python files already formatted |
| Mypy | Passed; 67 source files |
| Public contracts | All 16 JSON schemas and generated contract documentation match the models |
| Installed wheel | Built, installed in a fresh environment, generated fixtures and completed all three demo paths from outside the repository |
| Installed happy demo | Published all nine certified metrics; **26/26 reconciliation checks** passed; audit chain intact |
| Installed failure/injection demos | Timeout retried; malformed data stopped at review with no publication; injection flagged, 68 mappings unchanged, no planted text in checked outputs |
| OTLP | Local HTTP collector received and decoded the emitted protobuf span; covered by the full suite |
| Git whitespace check | Passed |

The full-suite run initially exposed one outdated expectation: a reviewer selected the same target
already proposed, but the test counted that as a change. The corrected assertion checks zero actual
overrides. Genuine changes retain separate positive regression coverage. The final suite above is
the complete rerun after that correction.

## Operational changes and remaining work

- Apply migration **0003** with `uv run poe migrate` before using an existing state database.
  Existing publication rows are marked complete and verified on reuse. See
  [ADR-0012](adr/0012-recoverable-publication.md) for recovery and cancellation semantics.
- Register explicit `ConnectionSpec.category_domains` when approved category labels are needed;
  absent domains intentionally suppress labels. Review schema restrictions before registering a source.
- Implementation/configuration changes can now rewind a paused run and require fresh review.
  SQLite transaction serialization trades concurrency for correct audit/publication ordering.
- Actual Docker/Compose execution remains unavailable in this environment. The new CI smoke job
  checks migrations, authenticated MCP access, refusal without valid credentials and persistence
  across restart. Hosted CI, including PostgreSQL 16, has not run because no remote is configured.
- Live Claude Code/Skill efficacy and judge benefit remain unproven. Use
  [the transcript protocol](skill_comparison.md) and `python -m evals.judge_eval --mode record`
  when the required sessions/credentials exist. The replay report correctly keeps the judge opt-in.
- The local semantic executor covers the generated monthly simple/derived metric subset.
  `mf validate-configs` and actual MetricFlow runtime queries still need their separate environment.
- Production OAuth/JWT, live warehouse adapters and warehouse deployment remain v0.2 scope;
  external telemetry deployment is environment-specific. None is claimed complete by these fixes.

No further numbered audit defect is knowingly left without a fix. The external verification items
above remain acceptance limits, rather than passing results.
