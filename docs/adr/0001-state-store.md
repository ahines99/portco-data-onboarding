# ADR-0001: Workflow state in SQLAlchemy + Alembic; Postgres reference, SQLite for demo and tests

- Status: accepted
- Date: 2026-09-23

## Context
The handoff mandates PostgreSQL as the workflow source of truth, and also asks for a one-click local
demo. Requiring Docker for the demo raises the bar for anyone reviewing the project.

## Decision
All state goes through SQLAlchemy Core repositories (`src/adapters/repositories.py`) and Alembic
migrations (`migrations/`). PostgreSQL is the reference store: docker-compose, a CI service container,
and a database-enforced append-only audit trigger. SQLite is supported for the demo and the fast test
suite. `JSON().with_variant(JSONB, "postgresql")` and portable `Uuid` columns keep one schema.

## Alternatives considered
- Postgres only: faithful to the handoff, but the demo would need Docker.
- SQLite only: simplest, but not the handoff's target, and it has no database-enforced append-only.

## Consequences
Two dialects to keep compatible. A test asserts that the migration equals the metadata, and a
Postgres CI job runs the migration, the trigger and a workflow run against Postgres.

## Evaluation
`tests/test_persistence.py` (SQLite) and `tests/test_postgres.py` (CI Postgres).
