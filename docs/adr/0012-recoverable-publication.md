# ADR-0012: Recoverable publication with certification and execution fencing

- Status: accepted
- Date: 2026-09-27

## Context

A database receipt and a filesystem rename cannot commit atomically. The old receipt-first path
could permanently reuse a receipt whose directory was never published. An abandoned worker could
also finish publication after its execution had been cancelled, and cached step output skipped
filesystem integrity checks.

## Decision

Migration 0003 adds a prepared/complete publication state. A transaction reserves the version;
the worker stages private files and then finalizes under run/publication locks. Finalization
reloads effective bundle and per-metric approvals and checks the current execution owner, status,
lease, deadline and cancellation. The worker checks ownership again after rename and removes new
output if execution expired during that operation. Publication always executes its validation
path, even when upstream steps are reused.

A retry reconstructs the same reserved version. A directory left by a crash after rename can be
completed only if its files and certification metadata match exactly. A completed publication
whose files have disappeared or changed fails closed; it is not silently overwritten. Content
hashes, relative paths, containment and symlinks are checked before publication or reuse.

Cancellation serializes with finalization. Once the current publication is complete, cancellation
is too late and is rejected. A later rerun can still be cancelled before its own publication step;
previous certified output is retained.

SQLite transactions use `BEGIN IMMEDIATE` so audit-head reads and subsequent appends are serialized.
PostgreSQL uses row locks. This provides an explicit ordering for audit appends, cancellation and
publication decisions without holding a database lock through the dbt build.

## Consequences

The filesystem and database still lack a distributed transaction. Crash recovery reconciles their
state on retry; an abrupt process exit can leave inert private staging directories for later
operational cleanup. Existing rows migrate to complete and are integrity-checked on reuse.
SQLite serializes transactions more broadly, limiting throughput compared with PostgreSQL.

Tests in `tests/test_publication_recovery.py`, `tests/test_engine_leases.py` and
`tests/test_postgres.py` cover failure windows, stale certifications, content tampering,
concurrency, cancellation and recovery.
