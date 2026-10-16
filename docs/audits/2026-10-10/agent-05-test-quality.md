# Agent 5/10: test assurance, evaluation integrity, and CI

Audit date: 2026-10-10. Read-only review of tracked files; one isolated evaluator probe wrote `agent-05-gate-probe.json`. No duplicate full test run. Parent agent owns current pytest, golden-eval, hosted-CI verification, and final counts. Findings below distinguish observed harness behavior from recommended assurance improvements.

## Assessment

The repository has meaningful tests, rather than a merely large test count: real generated SQL execution against independent financial expectations, failure and recovery tests, publication file-byte verification, tamper tests, actual PostgreSQL source extraction, real OTLP HTTP export, and container restart/recreation checks. CI runs SQLite, security, PostgreSQL, golden evaluation, two unfamiliar-schema corpora, Linux/Windows wheel smoke, actual container smoke, Auth0 JavaScript tests, lint/types, and dependency/image audits (`.github/workflows/ci.yml:21-196`). The main gap is composition: tests separately verify caching, approval checks, lease recovery, redaction, and export, but do not verify the invariants across these boundaries.

## Concrete findings

### T1 — P2: full evaluation can pass with entire required dimensions absent

`evals/run.py:97-110` rejects globally empty evaluations but skips a configured dimension when its rate is `None`. `evals/thresholds.yaml:2` also requires only 25 passing cases while the current corpus contains 37. The existing regression (`tests/test_eval_regressions.py:29-40`) covers wholly empty reports and failed partial reports, not missing dimensions or a reduced full population.

Reproduction: invoke `gate(..., full_run=True)` using the actual thresholds, a 37/37 report with all other dimensions passing, and both `permission` and `evidence` set to `{passed: 0, total: 0, rate: null}`. It returns `[]` failures. A 25/25 report also passes. Exact inputs/results are in `agent-05-gate-probe.json`.

Impact: accidental deletion/reclassification of checks can weaken the full CI gate without a failure. This is a reproducible latent gate weakness, not a claim that the current 37-case run omitted its security checks.

Fix: full runs must enforce positive check populations for each required dimension and the expected case/check identity set, including unique case IDs. Partial `--case` runs can continue reporting missing dimensions as not evaluated. Add three tiny harness regressions: remove one required dimension; remove a required case; typo/unknown dimension. Each full run must fail with an explicit missing-coverage reason. Pin required identities or versioned coverage metadata, not only a magic count.

### T2 — P1 remediation priority: PII assurance omits the failure telemetry surfaces that need protection

`evals/cases.yaml:134-139` titles G17 “PII canaries never leak through any surface”, but `evals/checks.py:52-67,408-412` scans findings, artifacts, audit, pending items, generated files, and a report. It does not capture standard logging, stderr, trace exception events/status descriptions, or actual MCP transport responses. The broader security helper (`tests/security/test_security.py:28-59`) adds evidence/metrics/published files but still omits those telemetry paths.

The existing injected-secret crash regression (`tests/test_workflow.py:198-214`) deliberately raises `ValueError("secret detail 123-45-6789")`, then asserts only that `run.error` is sanitized. `tests/test_cli_and_observability.py:86-96` checks a direct structured log event; its span test (`:109-130`) checks a successful run and span attributes. Real OTLP test (`tests/test_otlp_export.py:11-65`) emits a success-only span. These checks therefore do not contradict the exception/log leak found by the security reviewer.

Fix: extend the existing failing-step test, rather than add another happy-path suite. Inject a synthetic canary, capture standard logger text + stderr + span events/status + OTLP payload + returned MCP error, and assert direct canary byte absence across all sinks. Keep an independent exact-canary assertion in addition to `PiiGuard.scan`; using the same classifier as both guard and sole oracle can mask correlated defects. Also test exception causes and structured `exc_info`, not only explicitly supplied attributes. Until covered, narrow the G17 report title to its actual surfaces.

### T3 — P1 remediation priority: direct helper and simulated recovery tests miss authority loss across cache/worker boundaries

Generation's approval regression (`tests/test_generation.py:84-101`) copies persisted approvals, marks those copies revoked, and directly calls `generate_artifacts(ctx)`. It never passes through workflow cache reuse. The independent cache regression (`tests/test_workflow.py:142-161`) exercises only still-valid authority. Combine them: warm a generation cache, revoke/expire the actual persisted mapping approval, resume/rerun through the public service/MCP API, and require renewed review before any generation reuse.

Lease recovery (`tests/test_engine_leases.py:76-85`) simulates a dead worker by replacing DB lease fields, then resumes successfully. It does not leave an old worker alive. Publication fencing (`tests/test_publication_recovery.py:215-239`) changes the persisted owner during a write using one context. Concurrent publication (`:330-336`) calls the same context from two threads. Neither schedules old-worker completion after a new worker claims the lease. This matters for the worker-identity defect found elsewhere in this audit.

Fix: use Events/Barriers, not sleeps: worker A enters a blocking step; expire its lease; worker B claims and blocks; release A first; assert A cannot publish, append completed output, fail B's run, release B's lease, or alter B's current step. Run the same small scenario on SQLite and PostgreSQL. Add an approval-expiry/resume case that expects a fresh review gate, not a terminal failure or old cached approval.

These are coverage causes of independently reproduced defects, not additional separate product vulnerabilities to double-count.

### T4 — P3: golden report provenance cannot establish which source state was evaluated

`evals/run.py:86-94` records timestamps, elapsed time, case results, and dimensions. `:160-174` writes latest reports without source commit, dirty-state/source hash, cases/threshold hashes, lockfile hash, or runtime versions. A copied latest report therefore cannot independently substantiate current-revision claims. The unfamiliar benchmark already records commit and service-source hashes (`evals/unfamiliar_benchmark.py:254-271`), establishing a useful pattern, although adapters, ontology, and configuration also affect results.

Fix: add report provenance once per run: commit + dirty state, digest of relevant source/config/case/threshold/lock inputs, interpreter/OS, package versions or lock digest, and invocation/selection. Upload pytest JUnit alongside eval reports in CI. Link the exact CI run for current hosted claims. This is evidence-strengthening; it does not invalidate correctly linked historical runs.

## Minimal regression matrix

| Priority | Boundary to protect | Smallest useful test / invariant | Where to run |
| --- | --- | --- | --- |
| P1 | Exception redaction × transport/export | One failing workflow step with synthetic secret, inspect stderr/logs/MCP error/span events/status/decoded OTLP | Unit/integration; reuse local OTLP collector |
| P1 | Approval validity × generation cache | Warm cache, revoke or expire DB approval, resume through facade; cache cannot bypass renewed review | SQLite; one PostgreSQL integration variant |
| P1 | Lease takeover × late result | Deterministic two-worker barrier schedule; stale worker has zero authority over successor state | SQLite + PostgreSQL |
| P1 | SQL CTE lexical scope × allowlist | Allowed CTE, sibling/nested shadowing, qualified/unqualified references, denied physical table beneath reused alias; evaluate accepted queries against fixture | SQL guard unit/adapter tests |
| P2 | Approval expiry × pause/resume | Review accepted before expiry, resume after expiry; fresh review items emitted and run recoverable | Workflow integration |
| P2 | Import roundtrip × supported scalar types | Exact source-to-snapshot equality for timestamps with fractional seconds, booleans, decimals, null vs empty; accepted manifest must remain resolvable | CSV unit + actual PostgreSQL integration |
| P2 | Identifier normalization × atomic registration | Case variants, duplicate normalized names, empty table, mixed-case schema; either exact roundtrip or atomic rejection with no registration | Import tests |
| P2 | Receipt growth × resolver bounds | Many narrow columns/tables with tiny row counts; successful import implies successful resolve; reject before commit if receipt exceeds supported limit | Import tests, no huge payload needed |
| P2 | Evaluation coverage × gate | Required dimension/case removal and unknown dimension all fail full gate; legitimate selected case reports partial status | Harness unit |
| P2 | Scale × profiling/join inference | Increasing row count and column/table count separately; capture query count, bytes/RSS, p50/p95 and responsiveness, verify capped/rejected cases retain no partial registration | Dedicated benchmark lane after baseline |

## Assurance boundaries and improvements

- Metric reference coverage is explicitly 100% branch coverage for `src.domain.metrics_reference` (`pyproject.toml` task `cov-metrics`, CI `:45-46`). It is not a repository-wide coverage guarantee. Keep this targeted requirement; prioritize boundary regressions over an arbitrary whole-repository percentage.
- Financial testing has genuinely useful independent microcases: month-end exclusivity, negative/zero values, currencies, undefined ratios (`tests/test_metrics_reference.py:24-140`), and generated semantic expression mutation (`tests/test_semantic_execution.py:103-118`). Preserve these when refactoring; a snapshot alone would not replace execution evidence.
- Current golden latency gates (`evals/checks.py:662-667`) bound single small fixture runs, with overall evaluation <=600 seconds. `tests/test_integrity_and_contracts.py:135-140` bounds fixture generation size/time. These do not establish production-size throughput, memory, query amplification, or concurrent tail latency. Set a benchmark baseline by rows AND schema width; require agreed regression tolerances rather than brittle shared-runner absolute timings.
- Frozen unfamiliar benchmark CI uses `--enforce-safety` and intentionally no accuracy floor. That is documented, reasonable safety evidence, not a product utility/generalization gate. Agent 8 owns that assessment.
- Default local `not postgres` tests exclude PostgreSQL. Container and PostgreSQL assurance must be tied to the exact hosted commit; local green tests cannot substitute. Parent confirms current hosted evidence separately.
- Add a compact rule-based workflow model only after immediate deterministic regressions: actions start/review/revoke/expire/resume/rerun/cancel/claim, with invariants that completed publication has current bound approvals and stale leases never mutate current state. This explores action sequences that the current transition-table test cannot cover. Do not introduce randomness or sleeps into concurrency regressions.
- Mutation probes are high value here: disable cached-path auth check, omit worker-token comparison, remove one redaction sink, or drop one required eval dimension. Each corresponding regression must fail. Limit mutations to critical invariants rather than broadly doubling CI runtime.

## Primary-source research

- [Hypothesis stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html) documents generating action sequences and checking invariants, which directly fits approval/lease/cache transitions. Recommendation is a scoped addition; Hypothesis is not currently a project dependency.
- [pytest logging capture](https://docs.pytest.org/en/latest/how-to/logging.html) provides `caplog` records/text and logging-level control, suitable for checking standard logging in the failure test.
- [pytest stdout/stderr capture](https://doc.pytest.org/en/7.3.x/how-to/capture-stdout-stderr.html) distinguishes Python stream capture from file-descriptor capture (`capfd`), relevant when subprocess/native-library diagnostics must also be checked. For a service subprocess, explicitly collect stdout/stderr rather than assuming in-process logging capture covers it.

No tracked implementation changes were made.
