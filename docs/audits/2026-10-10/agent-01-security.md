# Agent 01: security, authorization, tenant isolation and disclosure audit

Date: 2026-10-10. Read-only review of tracked files; all experiments used a temporary directory, a synthetic email sentinel, and an in-memory telemetry exporter. No external identity/production service was contacted. Reproduction script: `var/audit-2026-10-10/security_probes.py`; run with `.venv/Scripts/python.exe var/audit-2026-10-10/security_probes.py`.

## Scope and conclusion

Reviewed the MCP tools/resources/middleware, JWT/static verification, HTTP server/startup settings, Auth0 Actions, facade authorization, approval handling, policy/PII/identifier/SQL guards, source resolution, logging/tracing, and relevant security tests. No demonstrated JWT signature bypass, agent-to-reviewer escalation, raw source-row API, or cross-tenant run-content read was found. This is not a claim of proof or a live penetration test. Main agent owns full-suite execution.

The repository explicitly supports synthetic demonstration data; SECURITY.md says not to use real personal/company data, and docs/LIVE-DEPLOYMENT.md treats actual provider acceptance as unfinished. Severity below is calibrated to this current scope. The telemetry/logging findings should become release blockers before admitting sensitive source data.

## Verified findings

### SEC-01 (P2 now; high impact with sensitive data): trace exports bypass redaction

Locations: `src/observability.py:123` (automatic exception capture), `src/observability.py:107` (direct exporter), `src/workflows/base.py:319` / `:330` (workflow exception passes through span before application error handling).

`span()` calls OpenTelemetry `start_as_current_span()` with the defaults that record exceptions and set an error status. When an exception escapes a span, its message and stacktrace are copied into the exception event and its text is also copied into the span status description. Neither the logging `redact` processor nor `PiiGuardMiddleware` is on this path. The real workflow wrapper catches outside the span, so returning a safe tool error does not fix the export.

Reproduction: configure the actual project's tracing helper with `InMemorySpanExporter`, raise `ValueError` containing the synthetic sentinel inside `observability.span`, inspect the completed span. Both `trace_exception_event_contains_sentinel` and `trace_status_contains_sentinel` are true. No external exporter was used.

Impact: enabling the supported OTLP exporter can disclose driver/source exception contents or PII-bearing principal/attribute values to a telemetry sink. Current deployments should contain only synthetic data, and no actual leak to a configured collector was asserted.

Fix: set `record_exception=False, set_status_on_exception=False` on automatic spans; record safe exception type/code and safe status explicitly. Apply one exporter-boundary sanitizer/allowlist to span attributes, event attributes, links and status descriptions, including explicit caller `set_attribute` usage. Collector redaction is a useful additional control, but should not be the only barrier before data leaves this process.

Validation: expand existing OTLP localhost collector test with failure cases and synthetic email/card/DSN sentinels; parse the complete protobuf payload and assert no raw sentinel in any event, attribute or status field. Ensure error counts/type and correlation IDs still work. Confidence: high; executed against installed runtime.

### SEC-02 (P2 now; high impact with sensitive data): stdlib/SDK exception logs do not use the redactor

Locations: `src/observability.py:72` (plain root logging handler), `src/observability.py:73` / `:80` (redaction configured only for structlog), `src/capabilities/resources.py:23` (unexpected resource exceptions delegated to SDK).

`logging.basicConfig` emits plain Python logging records while only `structlog.configure` installs redaction. MCP SDK resource error handling uses standard `logger.exception`. An unexpected exception from a resource's storage/model read therefore logs its raw traceback and message through the unprotected handler. Application stdlib paths such as `facade._snapshot_metrics` also use `logging.getLogger(...).warning(..., exc_info=True)`.

Reproduction: start an in-process MCP client/server against a temporary service; inject a RuntimeError containing the synthetic sentinel into `service.artifact`; request `run://<uuid>/profile`; capture stderr. `unexpected_resource_exception_logs_raw_sentinel=true` while `resource_error_response_contains_sentinel=false`. This deliberately verifies log egress separately from the protected client response.

Impact: exception paths can write PII/credentials to local or provider logs even though normal tool responses and structlog tests pass. This is an egress-control gap, not a demonstrated cross-tenant client response leak.

Fix: route stdlib and structlog through a shared redacting formatter/processor on all effective output handlers, including formatted exception text; explicitly account for handlers preconfigured by uvicorn/MCP/dependencies. Add correlation-only unexpected-resource handling as defense in depth. Avoid making correctness depend on `basicConfig`, which can be a no-op if an earlier import installed handlers.

Validation: capture actual stderr for both direct stdlib logging and MCP resource failures with synthetic PII and DSN sentinels; verify redaction after third-party logging setup and under the deployed launcher. Confidence: high; end-to-end in-process MCP reproduction.

### SEC-03 (P2): unauthorized source calls perform source work before tenant authorization

Locations: `src/workflows/facade.py:144` resolves the connection before `:149` authorizes; `src/adapters/external.py:532` calls `ensure_fixture`; `src/adapters/csv_source.py:258` checks a complete snapshot hash before returning tenant metadata.

`start_run` obtains the owning company via a resolver that can generate fixture files or hash CSV snapshot files. A scoped caller thus triggers source work before receiving Forbidden. This also runs synchronously in the async tool path, so disk/CPU work can delay the single event loop.

Reproduction: fresh temporary fixtures root; principal `company_ids=('portco_a',)`; call `start_run(..., 'fixture:portco_b')`; `portco_b.duckdb` does not exist before and exists afterward even though the call raises Forbidden. No run is created and no cross-tenant source rows are returned. CSV preauthorization hashing is verified by code inspection, not a benchmark or extraction attempt.

Impact: tenant enforcement does not cover source materialization and integrity work. Other-tenant fixture variants can consume storage/CPU; registered snapshot existence and integrity can be distinguished through errors. The production workload gate/concurrency bounds limit the abuse and the finite synthetic fixtures limit current impact.

Fix: separate cheap server-owned metadata lookup from source materialization/integrity validation; authorize the resolved owner before any source access or creation; execute authorized expensive resolution work in the bounded worker path. Keep client-supplied `company_id` non-authoritative. Consider uniform not-found behavior for unauthorized registered connections.

Validation: denied cross-tenant fixture request must create no file or run; denied CSV request must not invoke hashing/open the source; authorized sources must retain integrity checks and schema-allowlist validation. Confidence: high for fixture side effect, high static confidence for CSV ordering.

### SEC-04 (P3): blocked resource responses lack the promised per-run security audit event

Location: `src/capabilities/guard.py:79` / `:80` resolves a run only from tool `arguments.run_id`, then `:84` raises for resources.

`resources/read` carries the target in `uri`, not tool `arguments`; therefore `_audit(None, 'pii_guard_blocked', ...)` silently does nothing. The exception also prevents normal resource accounting from running. Resource protection still blocks the response, but the run's persisted incident trail/metrics miss the event.

Reproduction: create a temporary run; inject a resource payload containing the sentinel; read `run://<run-id>/profile`; `pii_resource_rejected=true`, `pii_resource_block_audit_count=0`.

Fix: derive an authorized run context from run/evidence/finding URIs before output checking, preserving cross-tenant checks; use this context for blocked-read accounting. For tools creating runs, also use the result's run ID where safely available. Validation should check exactly one persisted event for denied PII output and no foreign-tenant audit mutation. Confidence: high.

## Strengths and existing coverage

- JWT verification pins RS256, validates issuer/audience/expiry/issued-at/lifetime, rejects token-directed JWKS URLs/critical headers, checks RSA size and explicit roles/tenant lists, caps token size and auth worker concurrency, and has real-signed-token negative tests.
- Production rejects static tokens, local identity fallback, principal injection, unauthenticated transport, non-TLS state DB, disabled reviewer separation, and fault injection.
- Tenant-scoped run reads use not-found semantics; the facade checks access before exposing artifacts/evidence; supplied approval IDs are server-resolved, gate/content/run-bound, expiry/revocation checked; agents cannot approve and a starter cannot self-approve.
- Auth0 Actions use administrator-owned metadata and constrain M2M clients to agent role; actual issuer MFA/token operational acceptance remains explicitly external.
- SQL is internally built from quoted/catalog-checked identifiers and AST-guarded. Profiling excludes unsafe generated-code identifiers and suppresses PII/sensitive extrema; category labels need explicit server-owned allowlists plus value/injection checks.
- dbt environment is allowlisted, sources are copied/read-only, paths are constrained, and generated artifacts require review/certification.
- HTTP limits body/session/idle/concurrency/workflow work; no unsupported claim of complete DDoS protection is made.
- Tests already cover forged/stale approvals, PII canaries, tenant scopes, schema allowlist widening, dangerous SQL readers, malicious identifiers, redaction helper behavior, JWT key rotation and startup policy.

## Documented risks, not newly claimed vulnerabilities

Static tokens/local wildcard principals are intentionally local development scope. PII classification is heuristic, and unhashed/low-entropy transforms need revisiting before real sensitive data. JWT revocation is bounded by short token expiry rather than instant revocation. DB/filesystem/local source operators remain trusted. `sslmode=require` encryption without hostname verification is disclosed in live deployment docs; prefer `verify-full` where the hosting endpoint supports it. Do not present these as undisclosed exploits.

## Research: primary sources used

- OpenTelemetry explicitly warns that exception messages can contain sensitive information: https://opentelemetry.io/docs/specs/semconv/http/http-exceptions/
- OpenTelemetry guidance on handling sensitive data and collector redaction: https://opentelemetry.io/docs/security/handling-sensitive-data/
- OWASP logging guidance recommends excluding/sanitizing access tokens, PII, credentials and database connection strings: https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- OWASP authorization guidance supports deny-by-default and permission enforcement on each request: https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
- MCP authorization specification requires intended-audience validation and secure token handling: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-06-18/basic/authorization.mdx

Recommendations are applications of these sources to observed code paths. No live-provider security verification was performed.
