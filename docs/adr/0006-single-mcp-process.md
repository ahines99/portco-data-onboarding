# ADR-0006: One MCP process with capability modules

- Status: accepted
- Date: 2026-09-23

## Decision
One `MCPServer` exposes the schema-profiler, mapping, dbt, catalog/publish and run-orchestration
capabilities, each registered from its own module (`src/capabilities/`). The handoff allows this for
the MVP; the capabilities should be split into separate servers only when their authorization,
lifecycle or deployment needs diverge. Snowflake, Airbyte and catalog MCP servers are v0.2 work.

## Consequences
There is one auth and tenant-scoping path, and one PII-guard middleware that sees every response.
