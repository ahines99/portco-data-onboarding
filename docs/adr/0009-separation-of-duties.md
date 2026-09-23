# ADR-0009: The agent and the reviewer are different principals

- Status: accepted
- Date: 2026-09-23

## Decision
Every principal carries a role (`agent`, `reviewer` or `admin`) and a tenant scope. Approving,
certifying and waiving require a human role. With `require_distinct_reviewer` on (the default), the
principal that started a run cannot approve it. Denials are audited in their own committed
transaction, so a rolled-back request still leaves a trace. HTTP principals come from bearer tokens;
stdio uses a configured local principal, which is an agent by default.

## Context
The agent drafts everything, so if it could also approve, the gates would be decorative. Tenants
must also be isolated: a principal scoped to one portfolio company must not see another's runs.

## Alternatives considered
- Trusting a `reviewer` claim in the tool arguments: rejected. The claim would be caller-asserted.
- Letting the agent approve LOW-risk items: rejected. What counts as low risk is exactly what a
  wrong mapping gets wrong.

## Consequences
Every demo and test needs two principals. Over HTTP, a token with no company list reaches no tenant
(`*` must be granted explicitly), and the HTTP app refuses to start without tokens.

## Evaluation
G23 (agent self-approval is forbidden through both the service and MCP), G30 (cross-tenant access),
and `test_reviewer_who_started_the_run_cannot_approve_it`.
