# Threat model

Scope: v0.1. The MCP server (stdio and authenticated HTTP), the workflow engine and services, the
DuckDB source adapter, the dbt sandbox and the local publish target.

## Assets
1. **Source data**, especially PII: names, emails, phone numbers, national ids, card numbers,
   dates of birth, free text.
2. **Approval integrity**: who approved what, bound to which content.
3. **Published artifacts and metric definitions** that portfolio reporting will trust.
4. **Credentials**: HTTP tokens and an optional Anthropic API key.
5. **The audit trail.**

## Trust boundaries
- **B1** Model ↔ MCP server: the model is untrusted and may be prompt-injected.
- **B2** MCP server ↔ domain services: typed calls, principal and tenant checks.
- **B3** Services ↔ source: read-only, aggregate-only, SQL-guarded.
- **B4** Reviewer ↔ system: the human decision channel.
- **B5** Generated SQL ↔ execution: sandbox only.

## STRIDE by boundary

| Threat | Boundary | Mitigation | Enforced by |
|---|---|---|---|
| **Spoofing**: agent poses as reviewer | B1/B4 | Principals come from bearer tokens (HTTP) or local config (stdio); roles are checked server-side | `tests/test_mcp.py::test_review_flow_guards`, G23 |
| **Spoofing**: forged approval id | B1 | Server-side lookup; approval bound to run and content hash | `test_review_flow_guards`, ADR-0004 |
| **Tampering**: content changed after approval | B4 | Subject hashes; stale approvals revoked; publish re-verifies | G24, `test_changing_a_mapping_after_certification_revokes_it` |
| **Tampering**: audit log edited | DB | Hash chain plus Postgres append-only trigger | `test_audit_chain_detects_tampering`, `test_audit_log_is_append_only_in_the_database` |
| **Tampering**: generated SQL writes to the source | B5 | Read-only attach of a copy; path check refuses targets outside the sandbox | `test_dbt_cannot_target_outside_the_sandbox`, G28 source unchanged |
| **Tampering**: SQL injection via the adapter | B3 | All SQL built internally from catalog-validated identifiers, then parsed by the SQL guard | `tests/test_adapter.py` |
| **Repudiation**: "I never approved that" | B4 | Approvals are immutable rows with reviewer, role, time and decisions; `approval_recorded` audit | Audit chain verification |
| **Information disclosure**: PII to the model | B1/B3 | Aggregate-only adapter; PII guard blocks any PII-shaped response; staging hashes or excludes PII | G17 canaries, `test_pii_guard_middleware_blocks_leaking_output` |
| **Information disclosure**: PII to the LLM judge | B1 | Aggregates only; prompt PII-scanned and withheld on any hit | `tests/test_judge.py::test_pii_in_prompt_is_withheld` |
| **Information disclosure**: cross-tenant reads | B1/B2 | Tenant scope on every read; other tenants' runs look like NOT_FOUND | G30, `test_cross_tenant_access_through_mcp` |
| **Information disclosure**: secrets in logs | all | `SecretStr`; structlog redaction; logs on stderr only | `test_redaction_processor_drops_secrets_and_pii`, `test_secret_settings_are_never_rendered` |
| **Information disclosure**: values in error messages | B1 | Typed error contract; internal errors return a correlation id only; dbt messages sanitized | `test_internal_errors_return_a_correlation_id_only` |
| **Denial of service**: runaway queries or dbt | B3/B5 | Per-query interrupt timer, per-step timeouts, dbt subprocess timeout | Engine and adapter code |
| **Elevation of privilege**: prompt injection in source metadata | B1/B3 | Source text is `UntrustedText`; injection heuristics flag and withhold it; state changes only through typed, principal-checked tools | G15, G16 |
| **Elevation of privilege**: the agent approves its own work | B1/B4 | Separation of duties (ADR-0009) | G23, `test_reviewer_who_started_the_run_cannot_approve_it` |
| **Elevation of privilege**: unknown or new action | B2 | Policy registry is an allowlist; unknown actions are denied | `test_unknown_action_is_denied` |

## Residual risks and v0.2 work
- **Static dev tokens.** HTTP auth uses static bearer tokens; production needs an OAuth/JWT
  verifier with audience validation (`validate_token_resource=True`).
- **PII heuristics.** Classification is pattern- and name-based. Unusual encodings (for example
  national ids without separators) can be missed; the PII guard is a second line, not a proof.
- **Hashing brute force.** Hashed low-entropy PII (phone numbers) can be brute-forced. Salt per
  company, or exclude, in v0.2.
- **Row-reading reconciliation.** Sandbox reconciliation reads rows from the disposable copy
  (non-PII columns only), inside deterministic code. It is never exposed, but it is process memory.
- **Live sources.** Warehouse-side least-privilege roles and network egress controls matter once
  Snowflake arrives.
