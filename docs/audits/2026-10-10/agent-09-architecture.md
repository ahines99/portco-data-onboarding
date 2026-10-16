# Agent 09 — Architecture, public API, contracts, configuration

Audit date: 2026-10-10. Read-only implementation audit; only ignored `var/audit-2026-10-10` artifacts were written. Focus: observable API semantics and high-leverage architecture improvements. The root agent owns full-suite and packaging checks; no duplicate full suite was run here.

## Assessment

The architecture is coherent for a governed, local-first data onboarding prototype: strict domain contracts, a central facade, persisted workflows, content-addressed artifacts, generated JSON schemas, and small MCP outputs with resource-backed detail. The most useful next changes are stronger operation boundaries and input/state invariants, rather than introducing more services or replacing the workflow engine. Four defects were reproduced, including a named test operation publishing a certified bundle and a validly parsed configuration leaving a run marked RUNNING without a worker.

All reproduction results are in `agent-09-probe.json`; runnable code is `agent-09-probe.py`. Probes used real SQLite stores, fixture A, the MCP in-process client, actual dbt build/reconciliation for the publication case, and Typer's CliRunner for the exit-code case. They used separate temporary roots. The first run encountered a Windows temporary-directory cleanup issue after the substantive probes; the retained JSON comes from a successful rerun with best-effort cleanup. No user database or existing publication was changed.

## Confirmed findings

### A09-1 — P2: `run_sandbox_tests` can publish instead of stopping at its advertised boundary

**Location:** `src/capabilities/tools.py:313-325`; related operation annotations at `:42-58,71`, and unrestricted facade resume at `src/workflows/facade.py:159-163`.

The tool documents that it builds and reconciles in a disposable sandbox and then pauses at certification. Its implementation calls `svc.resume(principal, rid)` without a stopping boundary. When a run is already waiting at certification and a reviewer has recorded a valid certification, a subsequent `run_sandbox_tests` invocation advances through publication. It returns a test summary with `status=complete`; it does not return the publication receipt or make that side effect explicit.

**Reproduction:** drove fixture A to the certification gate; recorded legitimate decisions as a distinct reviewer; switched back to the agent; invoked only `run_sandbox_tests`. Result: `is_error=false`, `status=complete`, one publication in state `complete`, and its published directory existed. All 97 dbt data tests had passed. This is a capability-scope defect, **not a certification bypass**: a valid reviewer approval was present throughout.

**Impact:** an agent or operator rechecking tests can cause publication unexpectedly. The project distinguishes a dedicated publication operation, including its explicit approval ID and risk annotations, but the broader continuation route makes the supposedly narrower operation state-dependent. The same design pattern merits checking in the other step-specific capability wrappers; the generic `resume_run` operation should clearly disclose whether it can publish.

**Fix:** give named capabilities a terminal allowed step and validate their starting phase. At minimum call resume with `stop_after=HUMAN_CERTIFICATION` for sandbox testing, then explicitly return an existing test report or a phase conflict when the run has already advanced beyond that boundary. A `stop_after` that is already behind `current_step` does not constrain the present engine, so a precondition is necessary. Keep a clearly documented general continuation operation if that behavior is desired.

**Regression:** on pending artifact generation, test failure, waiting-for-certification, validly certified, already complete, and cancelled runs, assert the permissible state transitions **and absence of new publication records/files** for `run_sandbox_tests`. Verify actual side effects, not just annotations or returned fields.

**Research:** MCP's official schema defines annotations as behavioral hints rather than enforcement. This makes server-side operation boundaries the appropriate fix; changing hints alone is insufficient. [Official MCP schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2025-06-18/schema.ts), [MCP annotation guidance](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/).

### A09-2 — P2: zero retry attempts strand runs in a false RUNNING state

**Location:** unconstrained settings at `src/settings.py:29-40`; limited cross-field check at `:69-74`; zero-iteration path at `src/workflows/base.py:299-302,360`; drive return at `:236-240`; lease release at `:222-224`.

`Settings(step_max_attempts=0)` is accepted. Retryable steps execute `range(1, max_attempts + 1)`, so none execute; `_run_step` returns `failed` without recording failure. `_drive` returns the unchanged run, and the outer engine releases its lease. The result says RUNNING even though execution has ended and no worker owns it.

**Reproduction:** real `svc.start_run(AGENT, 'fixture:portco_a')` under `step_max_attempts=0` returned `status='running'`, `lease_owner=null`, `error=null`, and zero attempts for every step. This is distinct from a transient in-flight run. Correcting configuration can permit recovery; with the same setting, resumes make no progress.

Other accepted values demonstrate the validation boundary is incomplete: `dbt_timeout_seconds=-100`, `step_timeout_seconds=-20`, `lease_margin_seconds=-200`, `approval_ttl_hours=-1`, and `sandbox_keep_attempts=-1` all construct successfully together. The existing nesting check only compares timeouts and does not imply positivity.

**Impact:** a deployment/environment typo passes startup validation and produces misleading workflow status or unusable approvals. This requires operator-controlled configuration; it is not a remote authorization issue.

**Fix:** enforce attempts >=1, nonnegative backoff, positive finite step/dbt timeouts and approval TTL, a nonnegative lease margin, and an explicit retention policy for zero sandbox attempts. Set `allow_inf_nan=False` for timing floats. Keep timeout nesting validation. Also make the engine's exhausted-loop fallback persist a failure (or enforce its invariant before claiming a run), so inconsistent state cannot silently escape even if a caller bypasses normal settings construction.

**Regression:** reject invalid environment values at Settings construction, exercise boundary values, and assert that a returned RUNNING status always corresponds to a valid execution owner. Include positive retry exhaustion separately from invalid configuration.

**Research:** Pydantic directly supports numeric `ge`/`gt` bounds and finite-number validation at fields; no additional configuration framework is needed. [Pydantic field constraints](https://github.com/pydantic/pydantic/blob/main/docs/concepts/fields.md), [Pydantic type constraints](https://github.com/pydantic/pydantic/blob/main/docs/api/standard_library_types.md).

### A09-3 — P2: CLI reports a failed workflow with success exit status

**Location:** `src/cli.py:112-123,242-248,252-262`; printer at `:78-92`.

The CLI maps thrown `DomainError`s to exit code 2, but the engine normally persists step failures and returns a `RunRecord` with FAILED status. `run`, `resume`, and `rerun` print that result and return normally. Therefore shell automation cannot distinguish an unsuccessful onboarding run from a successful invocation by process status.

**Reproduction:** supplied a real service with the existing fault injector set to `adapter.probe:unavailable`, one attempt, and invoked `portco run --fixture portco_a` through `CliRunner`. Output contained `status=failed` and `SOURCE_UNAVAILABLE`, but `exit_code=0`.

**Impact:** scripts using normal exit-code checks may proceed after a failed source validation/build instead of alerting or stopping. Human review pauses can legitimately remain successful results; FAILED should not share that convention.

**Fix:** centralize the mutation-command completion policy: print the run, then exit nonzero for FAILED (and explicitly decide/document the cancellation convention). Do not automatically give `portco status` a failure exit code just because it successfully inspected a failed run. Add optional structured JSON output as a follow-up usability improvement for callers that need to distinguish pending/review/complete.

**Regression:** real fault injection for `run`, `resume`, and `rerun` must produce nonzero exits; expected NEEDS_REVIEW and requested PENDING stops remain successful. Preserve domain-validation exit behavior and useful run IDs in failure output.

**Research:** Click's official CLI reference identifies zero as successful completion and positive exit codes as errors. [Click exit-code guidance](https://click.palletsprojects.com/en/stable/command-line-reference/).

### A09-4 — P3: certification accepts invalid decision strings and classifies client mistakes as internal errors

**Location:** `src/capabilities/tools.py:169-173,194-197`; generic exception mapping at `src/capabilities/common.py:76-86`; analogous CLI parsing at `src/cli.py:212-220`.

`certify_run` declares `bundle_decision: str` and `metric_decisions: dict[str, str]`. Its exposed input schema permits arbitrary strings, but implementation later constructs `ReviewDecision(...)`. An invalid value raises ValueError and is turned into an INTERNAL error with a correlation ID. In contrast, ordinary mapping review uses the typed `DecisionIn` enum. The certification docstring permits approve/reject, while the underlying enum additionally includes an override choice that this route cannot supply meaningfully.

**Reproduction:** an authorized reviewer at a genuine certification gate called `certify_run(..., bundle_decision='typo')`. MCP accepted the input shape; the tool returned `is_error=true`, `code='INTERNAL'`, `retryable=false`. No approval was created by the invalid call.

**Fix:** declare the exact allowed decision Literal/enum on both bundle and metric values, reject unknown input fields where appropriate, and convert CLI YAML syntax/item/value validation failures into clear `ValidationFailed` diagnostics. Preserve actual server exceptions as INTERNAL.

**Regression:** inspect emitted tool schemas for the decision enum; test invalid bundle values and invalid values for a known metric; verify these report input validation without exception-level server crash logs or persistent approval changes. Add malformed CLI review packets such as scalar list entries and invalid decision names.

## Targeted maintainability recommendations

1. **Expose the existing review-reopen control to real operators.** The engine and facade support `reopen_reviews=True` (`src/workflows/base.py:466-487`, `src/workflows/facade.py:164-176`), but `portco rerun` has no corresponding option (`src/cli.py:252-260`), and the MCP surface exposes neither rerun nor reopen. An unchanged packet therefore retains prior approvals through the normal CLI rerun. Add an explicit reviewer-only reopen command/option with clear revocation output. This is an operator capability gap, not a missing engine mechanism. Preserve the current default reuse behavior.

2. **Test API semantics as a phase matrix.** Existing `tests/test_mcp.py` checks schemas, annotations, invalid approvals, and the happy-path ordering. Add small transition tests for each named operation at every plausible run state. This is the highest-return way to prevent accidental broader work as adapters and workflows grow. Pair status assertions with publication/approval/audit effects; the A09-1 case would pass a test checking only that a successful test report was returned.

3. **Keep contract versions meaningful at the boundary.** Domain artifacts consistently use strict `Contract` models and versioned schema fields, while MCP transport schemas use many unbounded strings and plain BaseModel. Introduce constrained transport enums/IDs where they guide clients, and add compatibility snapshots of emitted MCP input/output schemas alongside the existing domain schema drift checks. Avoid pretending this requires a new service layer.

4. **Preserve the current architecture until operational requirements justify splitting it.** Single-process MCP and DuckDB snapshots are documented design choices. There is no evidence here that introducing a queue, distributed service mesh, or generic plugin framework would fix the demonstrated defects. First make capability scope explicit, reject invalid configuration before side effects, and give operators accurate errors/status.

## Scope limits

This audit did not re-run the root's full tests, PostgreSQL integrations, or packaging smoke; it did not claim production concurrency/load validation. It reviewed architecture/contracts/configuration directly and executed four isolated reproduction cases. Existing reports cover authentication, leases/cache authorization, source ingestion, financial correctness, performance, and release delivery; those findings are intentionally not repeated.
