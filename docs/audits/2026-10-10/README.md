# Ten-agent audit evidence package

Start with the [consolidated audit](../../AUDIT-2026-10-10.md). Audited application commit: `e1f8e36936f832b019dbd9418994ea95dc47f7a5`.

This directory preserves ten specialist reports, selected synthetic evidence and small executable reproductions. Application code, frozen evaluation inputs and earlier release evidence were not modified. Statements in specialist notes that the working tree was clean describe their original audit runs, before the coordinator added this report package.

## Evidence

- [Verification summary](evidence/verification.json): fresh local check results and exact historical hosted-CI identity.
- [Workflow reproductions](evidence/agent-02-repros.json): cached approval, stale-worker ownership and expiry/recovery outcomes. The machine-specific temporary path was omitted; observed results are unchanged.
- [Financial reproductions](evidence/agent-06-probe-results.json): generated SQL and actual dbt/reconciliation reports for rejected-join and noncanonical-category cases.
- [Generic-key scope impact](evidence/generic-id-scope-impact.json): source SQL, real inference, simulated mapping/filter approvals, generated SQL and incorrectly filtered customer output.
- [Standalone mapping probe results](evidence/agent-08-probe-results.json): rerunnable generic-key exclusion and judge-metadata demonstrations.
- [Optional judge rerank](evidence/judge-stale-metadata-repro.json): stale target-specific safety metadata after an allowed offline selection.
- [API/configuration probes](evidence/agent-09-probe.json): test-tool publication, invalid configuration, CLI exit status and malformed decision handling.
- [Evaluator gate inputs/results](evidence/agent-05-gate-probe.json): empty required dimensions and reduced full-case population both incorrectly accepted.
- [Performance kernels/import](evidence/agent04_benchmark.json) and [event-loop contention](evidence/agent04_eventloop.json): measured observations, including negative optimization results and limitations.
- Fresh pinned [v1](evidence/frozen-v1.json) and [v2](evidence/frozen-v2.json) regression/qualification reports.
- [Dependency audit](evidence/dependency-audit.json): zero known vulnerabilities among 121 auditable installed dependencies, with the application itself explicitly skipped.

Original stdout/stderr logs, pytest JUnit, isolated databases, generated dbt projects and larger temporary outputs remain in ignored `var/audit-2026-10-10/` or the temporary paths described in the notes. They are not part of this package. No real business data, credentials or external telemetry were used in the probes.

## Reproduce the important mechanisms

Run from the repository root using the project's Python 3.12 environment. The probes use existing development/test helpers and synthetic data. They demonstrate the audited defects; they are not repaired production code or a replacement for regression tests. Some deliberately inject crashes, expiry or scheduling changes into their own temporary state. They never target an existing user database.

```powershell
uv sync --all-extras --frozen
uv run --frozen python docs/audits/2026-10-10/probes/security_probes.py
uv run --frozen python docs/audits/2026-10-10/probes/agent-02-repros.py
uv run --frozen python docs/audits/2026-10-10/probes/agent-06-probe.py
uv run --frozen python docs/audits/2026-10-10/probes/agent-08-probe.py
uv run --frozen python docs/audits/2026-10-10/probes/agent-09-probe.py
uv run --frozen python docs/audits/2026-10-10/probes/agent04_eventloop.py
```

The financial and API probes invoke dbt. The workflow/financial probes retain their diagnostic temporary state; output locations are printed. Rerunning writes new observations under `var/audit-2026-10-10/`, leaving this package's recorded JSON unchanged. Portable probe copies change only repository discovery/output destinations from the specialists' scratch scripts.

The optional `probes/agent04_bench.py` performs several insertion/import trials and takes several minutes. Run it separately on an otherwise idle machine for comparable performance evidence. Recorded October measurements ran alongside other audit work. The original measurement driver had a bind-parameter error after insertion/import measurements; it was corrected and the remaining phases rerun. The retained driver includes that correction; the evidence records this history rather than presenting it as a repository failure.

The ingestion report also contains minimal SQL and CSV reproductions. The evaluator-gate JSON supplies exact synthetic reports used against the real `gate()` function.

## Interpreting results

The local suite's 674 passing tests, the 16 targeted coverage tests, the 37 golden cases, and hosted jobs have overlapping populations. Do not sum them. One local input-symlink test was skipped because the Windows account cannot create symbolic links; 15 PostgreSQL cases were deselected. Docker/PostgreSQL integration evidence comes from the linked September 28 CI run on the identical source, not a new local October run.

Priority is consolidated in the main report. A specialist's context-specific P1 performance rating is not a claim that a vulnerability was remotely exploited. Synthetic fault injection, static reasoning, calculated latency floors, observed local benchmarks and live-provider acceptance are distinct evidence categories throughout this package.
