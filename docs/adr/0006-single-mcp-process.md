# ADR-0006: One MCP process with capability modules

- Status: accepted
- Date: 2026-09-23

## Decision
One `MCPServer` exposes the schema-profiler, mapping, dbt, catalog/publish and run-orchestration
capabilities, each registered from its own module (`src/capabilities/`). The handoff allows this for
the MVP; the capabilities should be split into separate servers only when their authorization,
lifecycle or deployment needs diverge. Snowflake, Airbyte and catalog MCP servers are v0.2 work.

## Context
The handoff lists several capability servers (profiler, mapping, dbt, catalog, orchestration). They
share one principal model, one tenant scope and one audit log.

## Alternatives considered
- One MCP server per capability: rejected for the MVP. It would multiply auth configuration, and the
  PII guard would have to be deployed and kept consistent in five places.
- A single tool that takes a "command" argument: rejected. Typed tools with annotations are what let
  clients reason about read-only versus destructive calls.

## Consequences
There is one auth and tenant-scoping path, and one PII-guard middleware that sees every response
and records per-run tool calls and evidence reads. Splitting later is mechanical, because each
capability module registers only against the server object it is given.

## Evaluation
`test_tools_have_schemas_and_consistent_annotations`, the PII-guard middleware tests, and G30
(cross-tenant access through MCP).
