# ADR-0009: The agent and the reviewer are different principals

- Status: accepted
- Date: 2026-09-23

## Decision
Every principal carries a role (`agent`, `reviewer` or `admin`) and a tenant scope. Approving,
certifying and waiving require a human role. With `require_distinct_reviewer` on (the default), the
principal that started a run cannot approve it. Denials are audited in their own committed
transaction, so a rolled-back request still leaves a trace. HTTP principals come from bearer tokens;
stdio uses a configured local principal, which is an agent by default.

## Evaluation
G23 (agent self-approval is forbidden through both the service and MCP), G30 (cross-tenant access),
and `test_reviewer_who_started_the_run_cannot_approve_it`.
