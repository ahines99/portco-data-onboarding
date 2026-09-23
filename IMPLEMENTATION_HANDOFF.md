# 13. Autonomous Portfolio Company Data Onboarding Agent

## Implementation-agent handoff

### Mission
Profile unfamiliar portfolio-company data, infer entities and joins, map into a canonical PE ontology, generate dbt/tests/semantic artifacts, and route uncertain mappings for review.

### Definition of done
A credible MVP is not a chat demo. It must expose typed MCP capabilities, persist workflow state, preserve evidence/provenance, stop at approval boundaries, include at least one Agent Skill, and ship with integration tests. The demonstration should show a complete end-to-end run with both a successful path and a controlled failure/review path.

### Non-goals for v0.1
- Do not build autonomous irreversible actions.
- Do not let the LLM become the system of record.
- Do not hide deterministic calculations inside prompts.
- Do not create a generalized multi-agent framework before the primary workflow works.
- Do not optimize UI before evidence, contracts, and tests are stable.


## Reference architecture

Use a four-layer design:

1. **Data and capability layer**: source systems, deterministic calculation services, document/evidence stores, and domain APIs.
2. **MCP boundary**: small servers that expose typed tools, resources, and user-selectable prompts. MCP is the capability contract, not the business logic layer.
3. **Skill layer**: Agent Skills package procedural knowledge, review checklists, reference material, and scripts. A Skill should teach *how to perform the work*, not become a hidden database or hard-coded workflow engine.
4. **Workflow/orchestration layer**: state machine or durable workflow service coordinates steps, approvals, retries, parallel branches, and audit events.

**Why this split**
- Deterministic services own arithmetic, portfolio math, joins, permissions, and irreversible side effects.
- MCP gives the model a standardized, inspectable capability surface.
- Skills keep domain operating procedures version-controlled and progressively disclosed.
- The workflow engine owns state and recovery, preventing the LLM conversation itself from becoming the source of truth.

For local development use MCP over stdio or in-process tests. For deployed servers use Streamable HTTP behind authenticated ASGI infrastructure. Prefer the current stable Python MCP SDK v2 and Python 3.12+.



## Recommended stack

- Python 3.12
- `uv` for environment/package management
- MCP Python SDK v2
- FastAPI/Starlette only where non-MCP HTTP endpoints are needed
- Pydantic v2 for contracts
- PostgreSQL for operational state and audit logs
- pgvector or a managed vector store only where semantic retrieval is genuinely required
- Neo4j only for graph-heavy projects, not by default
- DuckDB/Polars for local analytical execution
- dbt for warehouse transformations where applicable
- Temporal, Prefect, or a small explicit state machine for durable workflows. Start with a simple state machine unless retries, timers, or distributed workers justify a workflow engine.
- OpenTelemetry for traces and metrics
- pytest + MCP in-process client tests
- Docker for reproducible deployment

Do not make the agent framework the center of the repository. Keep orchestration behind interfaces so Claude, another model, or a deterministic job can drive the same domain services.


## Project architecture

### MCP capability boundaries
- `snowflake-mcp`: expose the smallest governed capability surface needed for snowflake.
- `dbt-mcp`: expose the smallest governed capability surface needed for dbt.
- `airbyte-mcp`: expose the smallest governed capability surface needed for airbyte.
- `catalog-mcp`: expose the smallest governed capability surface needed for catalog.
- `schema-profiler-mcp`: expose the smallest governed capability surface needed for schema profiler.

**Decision:** prefer multiple narrow MCP servers only when capabilities have distinct authorization, lifecycle, or deployment needs. During MVP development, it is acceptable to expose them from one process behind separate modules. Split services later when operational boundaries justify it.

### Agent Skills
- `schema-profiling`: procedural knowledge for schema profiling.
- `canonical-pe-ontology`: procedural knowledge for canonical pe ontology.
- `dbt-modeling`: procedural knowledge for dbt modeling.
- `semantic-layer-generation`: procedural knowledge for semantic layer generation.
- `data-quality`: procedural knowledge for data quality.

**Decision:** Skills should contain checklists, decision rules, examples, and reference links. They should not embed secrets or act as mutable state. This follows the progressive-disclosure model: frontmatter advertises the Skill, the body provides procedure, and `references/` or `scripts/` provide deeper material only when needed.

### Primary workflow
1. **Connection validation**
2. **Schema profiling**
3. **Entity inference**
4. **Join inference**
5. **Canonical mapping**
6. **Artifact generation**
7. **Automated tests**
8. **Human certification**
9. **Publish**

### Human approval boundaries
- Read-only discovery
- Generated SQL runs in sandbox first
- Human certifies metrics/joins
- No raw PII in model context

## Data and state model

Use PostgreSQL as the workflow source of truth. Minimum tables:

```sql
create table workflow_runs (
  run_id uuid primary key,
  project_type text not null,
  status text not null,
  current_step text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  requested_by text not null
);

create table evidence (
  evidence_id uuid primary key,
  run_id uuid references workflow_runs(run_id),
  source_uri text not null,
  source_type text not null,
  as_of timestamptz,
  content_hash text not null,
  metadata jsonb not null default '{}'::jsonb
);

create table findings (
  finding_id uuid primary key,
  run_id uuid references workflow_runs(run_id),
  finding_type text not null,
  statement text not null,
  confidence text not null,
  assumptions jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table finding_evidence (
  finding_id uuid references findings(finding_id),
  evidence_id uuid references evidence(evidence_id),
  relation text not null,
  primary key (finding_id, evidence_id, relation)
);

create table audit_events (
  event_id bigserial primary key,
  run_id uuid references workflow_runs(run_id),
  step text not null,
  actor text not null,
  event_type text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
```

```python
# src/domain/models.py
from __future__ import annotations
from datetime import datetime
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field

class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class EvidenceRef(BaseModel):
    source_id: str
    uri: str
    retrieved_at: datetime
    as_of: datetime | None = None
    excerpt_hash: str | None = None

class Finding(BaseModel):
    finding_id: str
    title: str
    statement: str
    confidence: Confidence
    evidence: list[EvidenceRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

class AuditEvent(BaseModel):
    run_id: str
    step: str
    event_type: str
    created_at: datetime
    actor: str
    payload: dict[str, Any] = Field(default_factory=dict)
```


### Project-specific contracts

```python
# src/domain/project_models.py
from datetime import datetime
from pydantic import BaseModel, Field
from .models import Confidence, EvidenceRef

class ColumnProfile(BaseModel):
    table: str
    column: str
    dtype: str
    null_pct: float
    distinct_count: int | None = None
    pii_class: str | None = None

class MappingProposal(BaseModel):
    source_field: str
    canonical_field: str
    confidence: Confidence
    rationale: str
    requires_review: bool

```

### Project-specific MCP tools

```python
# add to src/mcp_server.py
@mcp.tool()
def profile_schema(connection_id: str, schemas: list[str]) -> dict:
    return profiler.profile(connection_id, schemas, sample_rows=0)

@mcp.tool()
def propose_canonical_mapping(profile_id: str) -> list[dict]:
    return mapper.propose(profile_id)

@mcp.tool()
def generate_dbt_artifacts(mapping_id: str, approved: bool) -> dict:
    if not approved:
        return {"status": "approval_required"}
    return generator.dbt(mapping_id)

```


## Repository skeleton

```text
portco-data-onboarding/
├── pyproject.toml
├── README.md
├── .env.example
├── docker-compose.yml
├── src/
│   ├── mcp_server.py
│   ├── domain/
│   │   ├── models.py
│   │   ├── project_models.py
│   │   ├── services.py
│   │   └── policies.py
│   ├── adapters/
│   │   ├── repositories.py
│   │   └── external.py
│   ├── workflows/
│   │   ├── base.py
│   │   └── primary.py
│   └── observability.py
├── skills/
│   ├── schema-profiling/SKILL.md
│   ├── canonical-pe-ontology/SKILL.md
│   ├── dbt-modeling/SKILL.md
│   ├── semantic-layer-generation/SKILL.md
│   ├── data-quality/SKILL.md
├── tests/
│   ├── test_mcp.py
│   ├── test_workflow.py
│   └── fixtures/
└── docs/
    ├── architecture.md
    ├── data_contracts.md
    └── threat_model.md
```

## Package skeleton

```toml
[project]
name = "portco-data-onboarding"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "mcp[cli]>=2,<3",
  "pydantic>=2.9",
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "sqlalchemy>=2.0",
  "psycopg[binary]>=3.2",
  "httpx>=0.27",
  "structlog>=24.4",
  "opentelemetry-api>=1.27",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "ruff>=0.7", "mypy>=1.12"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```


## MCP server skeleton

```python
# src/mcp_server.py
from __future__ import annotations
from mcp.server import MCPServer
from pydantic import BaseModel, Field

mcp = MCPServer("Autonomous Portfolio Company Data Onboarding Agent")

class Health(BaseModel):
    status: str
    version: str

@mcp.tool()
def healthcheck() -> Health:
    """Return service health for diagnostics."""
    return Health(status="ok", version="0.1.0")

@mcp.resource("project://policies")
def policies() -> str:
    """Human-readable operating and safety policies."""
    return "Read-only by default. Material actions require explicit approval."

@mcp.prompt()
def review_run(run_id: str) -> str:
    """Create a user-controlled review prompt for a workflow run."""
    return f"Review workflow run {run_id}. Separate facts, assumptions, and recommendations."

app = mcp.streamable_http_app()
```


## Workflow skeleton

```python
# src/workflows/base.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETE = "complete"
    FAILED = "failed"

@dataclass
class RunState:
    run_id: str
    status: Status = Status.PENDING
    current_step: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

class Step(Protocol):
    name: str
    async def execute(self, state: RunState) -> RunState: ...

async def run_steps(state: RunState, steps: list[Step]) -> RunState:
    state.status = Status.RUNNING
    for step in steps:
        state.current_step = step.name
        try:
            state = await step.execute(state)
        except Exception as exc:
            state.errors.append(f"{step.name}: {exc}")
            state.status = Status.FAILED
            return state
        if state.status == Status.NEEDS_REVIEW:
            return state
    state.status = Status.COMPLETE
    return state
```


## Agent Skill skeleton

Create `skills/schema-profiling/SKILL.md`:

```markdown
---
name: schema-profiling
description: Use when the task requires the project's domain review procedure and evidence discipline.
---

# Objective
Produce a decision-ready output while preserving evidence, uncertainty, and human approval boundaries.

# Procedure
1. Read the relevant MCP resources before drawing conclusions.
2. Separate observations, calculations, assumptions, and recommendations.
3. Use deterministic tools for calculations.
4. Cite evidence identifiers for every material factual claim.
5. If evidence is insufficient, return `NEEDS_EVIDENCE` rather than guessing.
6. Escalate any material action to human approval.

# Output contract
- Summary
- Evidence-backed findings
- Assumptions
- Risks and counterarguments
- Recommended next actions
- Open questions
```


## Primary workflow implementation

```python
# src/workflows/primary.py
from dataclasses import dataclass
from .base import RunState, Status, run_steps

@dataclass
class FunctionalStep:
    name: str
    fn: callable

    async def execute(self, state: RunState) -> RunState:
        result = await self.fn(state)
        state.artifacts[self.name] = result
        return state

# Wire each project step to a domain service. The service returns structured data,
# not prose. A model-facing layer can summarize the structured artifacts later.
PROJECT_STEPS = ['Connection validation', 'Schema profiling', 'Entity inference', 'Join inference', 'Canonical mapping', 'Artifact generation', 'Automated tests', 'Human certification', 'Publish']

async def run_primary(run_id: str, services) -> RunState:
    state = RunState(run_id=run_id)
    wired = []
    for name in PROJECT_STEPS:
        service = services.for_step(name)
        wired.append(FunctionalStep(name=name, fn=service.execute))
    return await run_steps(state, wired)
```

## Policy pattern

```python
# src/domain/policies.py
from pydantic import BaseModel

class ActionDecision(BaseModel):
    allowed: bool
    requires_human_approval: bool
    reason: str

def check_action(action: str, risk_tier: str, has_approval: bool) -> ActionDecision:
    if risk_tier in {"high", "critical"} and not has_approval:
        return ActionDecision(allowed=False, requires_human_approval=True,
                              reason="Material action requires explicit human approval")
    return ActionDecision(allowed=True, requires_human_approval=False, reason="Policy satisfied")
```

## Evaluation strategy

Build evaluation before polishing prompts. Minimum evaluation dimensions:

1. **Tool correctness:** selected the right capability and supplied valid arguments.
2. **Evidence fidelity:** material claims resolve to stored evidence.
3. **Calculation fidelity:** numeric outputs match deterministic reference implementation.
4. **Permission fidelity:** forbidden actions fail closed.
5. **Uncertainty calibration:** insufficient evidence becomes an explicit unknown.
6. **Recovery:** tool timeout, malformed source data, and partial source outage produce controlled behavior.
7. **Cost/latency:** trace per-run model and tool costs.

Create a golden dataset of at least 25 representative cases before calling the MVP complete. Add adversarial cases for prompt injection, stale data, duplicate entities, contradictory evidence, and missing required fields.

## Testing skeleton

```python
# tests/test_mcp.py
import pytest
from mcp import Client
from src.mcp_server import mcp

@pytest.mark.anyio
async def test_healthcheck():
    async with Client(mcp) as client:
        result = await client.call_tool("healthcheck", {})
        assert result.is_error is False
        assert result.structured_content["status"] == "ok"
```


Add tests for:
- each project-specific MCP tool
- authorization/approval rejection
- workflow pause/resume
- idempotent reruns
- provenance links
- deterministic calculation fixtures
- at least one injected dependency failure

## Observability

Every run should emit:
- `run_id`, `step`, `tool_name`, `model`, latency, token/cost estimate
- input/output schema version
- evidence IDs read
- approval events
- failure/retry events
- final outcome and whether a human changed the recommendation

Never log secrets or raw sensitive payloads. Store hashes/IDs where possible.

## Security and threat model

- Use service accounts with least privilege.
- Treat all retrieved text as untrusted data, never as executable instructions.
- Keep credentials outside Skills and prompts.
- Enforce tenant/company scope server-side, not in natural language.
- Use read-only data access for discovery/analysis by default.
- For uploaded documents, retain immutable originals and derived text separately.
- Add explicit egress rules for any tool that can send email, create tickets, place orders, or modify production data.

## Milestones

### Milestone 0: contracts and fixtures
- Define source schemas and output contracts.
- Build synthetic or public-data fixtures.
- Write golden tests before agent orchestration.

### Milestone 1: deterministic core
- Implement adapters and calculation services.
- Persist runs, evidence, findings, and audit events.
- Demonstrate the workflow without an LLM where possible.

### Milestone 2: MCP surface
- Expose narrow typed tools/resources/prompts.
- Test with an in-process MCP client.
- Add auth and tenant scoping before remote deployment.

### Milestone 3: Skills and model reasoning
- Add the first procedural Skill.
- Introduce model reasoning only at judgment/synthesis steps.
- Preserve structured inputs/outputs around every call.

### Milestone 4: approvals and recovery
- Pause at human review points.
- Add retries, timeout handling, and idempotency.
- Exercise failure injection.

### Milestone 5: demo and portfolio polish
- One-click local demo with seeded data.
- Architecture diagram and threat model.
- 3-minute recorded demo script.
- README section titled `Why this is not just a chatbot`.

## Acceptance checklist
- [ ] Connection validation has a deterministic artifact, audit event, and failure path.
- [ ] Schema profiling has a deterministic artifact, audit event, and failure path.
- [ ] Entity inference has a deterministic artifact, audit event, and failure path.
- [ ] Join inference has a deterministic artifact, audit event, and failure path.
- [ ] Canonical mapping has a deterministic artifact, audit event, and failure path.
- [ ] Artifact generation has a deterministic artifact, audit event, and failure path.
- [ ] Automated tests has a deterministic artifact, audit event, and failure path.
- [ ] Human certification has a deterministic artifact, audit event, and failure path.
- [ ] Publish has a deterministic artifact, audit event, and failure path.
- [ ] Every material recommendation includes supporting evidence or explicitly says evidence is insufficient.
- [ ] All irreversible actions are disabled or human-approved.
- [ ] MCP tools have typed schemas and integration tests.
- [ ] At least one Skill is dynamically useful and not just duplicate prompt text.
- [ ] All arithmetic/financial/statistical calculations have deterministic tests.
- [ ] The demo can survive one injected tool failure.

## First implementation-agent tasks

1. Scaffold the repository exactly as shown.
2. Implement Pydantic contracts and PostgreSQL migrations.
3. Implement one adapter using fixtures, not live credentials.
4. Implement the primary deterministic service.
5. Expose only 2-4 MCP tools for the first vertical slice.
6. Create `schema-profiling` Skill.
7. Write five golden integration tests.
8. Run the complete workflow on fixture data.
9. Add the approval gate.
10. Only then connect additional sources or models.

## Handoff note to the coding agent
Do not broaden scope until the first vertical slice is demonstrably correct, auditable, and restartable. Prefer boring deterministic code over agent autonomy. Every time a model is introduced, document why a deterministic rule is insufficient and define an evaluation for that model-dependent decision.
