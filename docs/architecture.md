# Architecture

The system follows the handoff's four-layer design. Deterministic services own every number, join
and side effect. MCP is the capability contract. Skills carry procedure. A persistent workflow
engine owns state and recovery, so the conversation is never the source of truth.

## Layers

```mermaid
flowchart TB
  subgraph Agent["Model-facing (any MCP client, e.g. Claude Code)"]
    A[Agent] -->|reads| SK[Skills<br/>schema-profiling, canonical-pe-ontology,<br/>dbt-modeling, semantic-layer-generation, data-quality]
  end
  subgraph MCP["MCP boundary (src/mcp_server.py, src/capabilities/)"]
    T[Typed tools] --- R[Resources and templates] --- P[Prompts]
    G[PII guard middleware] --- AU[Bearer auth + tenant scope]
  end
  subgraph WF["Workflow layer (src/workflows/)"]
    E[Persistent engine<br/>input hashes, reuse, retries, timeouts, gates] --> F[Facade<br/>principals, policy, approvals]
  end
  subgraph Domain["Deterministic services (src/services/, src/domain/)"]
    S1[Connection] --> S2[Profiling + PII] --> S3[Entities] --> S4[Joins] --> S5[Mapping]
    S5 --> GA[Gate A: mapping review] --> S6[dbt + semantic generation] --> S7[Sandbox + reconciliation]
    S7 --> GB[Gate B: certification] --> S8[Publish]
    REF[Metric reference calculators] -.-> S7
    ONT[(Ontology v1<br/>ontology/*.yaml)] -.-> S3 & S5 & S6
  end
  subgraph Data["Data and state"]
    SRC[(Source: DuckDB fixtures<br/>read-only, aggregate-only adapter + SQL guard)]
    DB[(Workflow DB: Postgres / SQLite<br/>runs, step_runs, evidence, findings,<br/>approvals, append-only hash-chained audit)]
    BL[(Content-addressed artifact store)]
    SB[(Disposable dbt sandbox)]
  end
  A <-->|MCP| T
  T --> F --> E --> Domain
  S1 & S2 & S3 & S4 & S5 --> SRC
  E --> DB & BL
  S7 --> SB
```

## One run, end to end

```mermaid
sequenceDiagram
  autonumber
  actor Agent
  actor Reviewer
  participant MCP
  participant Engine
  participant Source as Source (read-only)
  participant Sandbox
  Agent->>MCP: start_onboarding_run(fixture:portco_a)
  MCP->>Engine: start (agent principal)
  Engine->>Source: probe, verify read-only, fingerprint
  Engine->>Source: aggregate-only profiling (counts, patterns, Luhn, containment)
  Engine->>Engine: entities, joins, mapping (deterministic, evidence-linked)
  Engine-->>MCP: NEEDS_REVIEW at mapping_review (22 items)
  Agent->>MCP: submit_mapping_review (agent)
  MCP-->>Agent: FORBIDDEN (separation of duties)
  Reviewer->>MCP: submit_mapping_review (explicit item decisions)
  MCP-->>Reviewer: approval_id (bound to mapping hash)
  Agent->>MCP: generate_dbt_artifacts(approval_id)
  MCP->>Engine: verify approval and input hashes, then resume or rewind stale steps
  Agent->>MCP: run_sandbox_tests
  Engine->>Sandbox: copy source, dbt build (subprocess), reconcile vs reference
  Engine-->>MCP: NEEDS_REVIEW at certification
  Reviewer->>MCP: certify_run(manifest_hash, metric decisions)
  Agent->>MCP: publish_run(certification_id)
  Engine->>Engine: verify certification, publish version, audit
```

## Run state machine

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> running: start / resume
  running --> needs_review: gate has undecided items
  needs_review --> running: resume (gate re-checks approvals)
  running --> pending: stop_after reached
  running --> failed: terminal error or retries exhausted
  failed --> running: resume (after the cause is fixed)
  running --> complete: publish succeeded
  needs_review --> cancelled: reviewer cancels
  complete --> pending: rerun_from(step)
```

## Key properties and where they live

| Property | Mechanism | Code |
|---|---|---|
| State outside the conversation | Every step persists output (content-addressed), evidence, findings and audit in one transaction | `src/workflows/base.py`, `src/adapters/repositories.py` |
| Idempotent reruns | Hashes bind upstream output, implementation, configuration and source policy; publish always verifies files | `WorkflowEngine._run_step`, ADR-0012 |
| Deterministic evidence ids | uuid5(run, source URI, content hash) | `src/workflows/contracts.py::make_evidence` |
| No raw PII in context | Aggregate-only adapter, PII guard middleware on every MCP response, hashed or excluded PII in staging | ADR-0003, `src/capabilities/guard.py` |
| Approvals cannot be faked or go stale | Server-side lookup, bound to the subject content hash, revoked on change | ADR-0004, `src/services/approvals.py` |
| The agent cannot approve | Role-based policy registry; the starter cannot approve their own run | ADR-0009, `src/domain/policies.py` |
| Generated SQL tested first | Disposable sandbox, read-only attach, exact reconciliation | ADR-0008, `src/services/sandbox.py` |
| Tamper-evident audit | Per-run hash chain; Postgres trigger forbids UPDATE/DELETE | `AuditRepository`, `migrations/versions/0001_initial.py` |
| Recovery | Error taxonomy, retries with backoff, per-step timeouts, fault injection | `src/domain/errors.py`, `src/adapters/faults.py` |

## Decisions
See `docs/adr/` (ADR-0001 to ADR-0012). [ADR-0012](adr/0012-recoverable-publication.md)
describes publication recovery and the point after which cancellation is too late.

Local reviewer identities rely on a trusted OS operator. Anyone who controls the local process,
configuration or state database is outside the agent-role boundary. The scripted demo uses synthetic
reviewer decisions; only a separately recorded human session establishes independent human review.
