# Local operations and recovery

Scope: synthetic fixtures and trusted local operators. Python 3.12 is required. Linux CI and Windows
verification are supported; macOS has not been verified. All state paths below belong to this project.

## First run

From the repository root, the following commands work in PowerShell and POSIX shells:

```text
uv sync --all-extras --frozen
uv run poe fixtures
uv run poe demo
```

`uv` must be on PATH for the CLI and `.mcp.json`. The demo deliberately uses synthetic reviewer
decisions. For real independent review, use the [agent walkthrough](agent_walkthrough.md).
The installed wheel requires no development extras for fixture generation, demo or stdio MCP.
The `postgres`, `llm`, and `telemetry` extras supply optional capabilities.

## Human review

```text
uv run portco run --fixture portco_a
uv run portco review RUN_ID --export review.yaml
```

Read each exported item and enter its decision. A plain `approve` must not contain an override.
`crm.opportunities.rev` is already proposed as opportunity amount; selecting it again is not a change.
Review units, transforms, PII handling, joins and proposed exclusions, then:

```text
uv run portco review RUN_ID --import review.yaml --reviewer alex
uv run portco resume RUN_ID
uv run portco review RUN_ID --export cert.yaml
```

Inspect the test report and every metric decision before filling and importing `cert.yaml` with
the same review command. Resume again to publish. Use `portco report RUN_ID --out report.md` and
`portco audit RUN_ID --verify` to inspect the result. Never auto-approve a real review for convenience.
The local CLI trusts the OS operator; separate principal names are not protection against an operator
who controls the process or database. HTTP tokens must represent separate roles and explicit tenants.

## Compose

Tokens are required. Generate two random tokens locally and configure the agent/reviewer mapping.
Example PowerShell (values stay in the shell, not source files):

```powershell
$agentToken = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$reviewToken = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$env:PORTCO_HTTP_TOKENS = "$agentToken=demo-agent:agent:portco_a;$reviewToken=alex:reviewer:portco_a"
docker compose --profile full up --build -d
```

POSIX:

```bash
agent_token=$(openssl rand -hex 32)
review_token=$(openssl rand -hex 32)
export PORTCO_HTTP_TOKENS="$agent_token=demo-agent:agent:portco_a;$review_token=alex:reviewer:portco_a"
docker compose --profile full up --build -d
```

Use `/healthz` for liveness; MCP is `/mcp` with a bearer token. Ports bind to loopback. The database
uses explicit `portco-postgres` storage; artifacts use `portco-data`. `docker compose --profile full
down` retains both. Adding `-v` intentionally destroys demo state: use only on a dedicated disposable
stack after checking its project name and volumes. Do not expose these development credentials publicly.
The container smoke automates reviewer decisions for synthetic CI data, not for the live user study.

## Upgrade and backups

Stop writes before backing up. Preserve the state database, `artifacts/`, `published/`, fixtures and
required configuration together. SQLite backups must use the SQLite backup API or a cleanly closed
database; copying only a live `.db` can omit WAL data. PostgreSQL requires a consistent database dump
and matching artifact backup while workflow writes are quiesced. Store tokens separately.

For an existing checkout, back up first, synchronize the frozen environment, then run
`uv run poe migrate`. Revision 0003 adds publication lifecycle state; existing rows become complete
and are checked for exact file integrity when reused. Rehearse on a copy before upgrading retained state.
Do not downgrade a populated production-like store to simulate rollback: restore its verified backup.

Publication receipts bind absolute paths. Restore to the same configured runtime path for this release;
moving retained state to a different machine/path is not a supported automatic relocation. Verify the
audit chain and every published artifact digest after restore, before resuming work.

## Recovery decisions

| Observed state | Next action |
|---|---|
| `mapping_review` / `certification` | Read pending items and supply current independent decisions |
| Expired/revoked approval | Export the current gate and review again; do not edit approval rows |
| Changed code/config/source policy | Resume may rewind and invalidate downstream approval; review refreshed evidence |
| `test_failures` | Inspect individual failures; fix inputs/mapping or record a justified explicit waiver |
| Transient dependency failure | Correct the cause, then resume; retry history remains in the audit trail |
| Worker crash with live lease | Wait for lease expiry, then resume through the engine |
| Prepared publication / crash after rename | Resume reconstructs or verifies the reserved version |
| Completed output missing or changed | Fail closed; investigate and restore exact verified backup; never forge a receipt |
| Cancellation after final publication | Cancellation is too late; retain the historical certified output |

Private `.vNNNN.tmp-*` staging directories can remain after abrupt exits. Clean them only with all
writers stopped and after confirming no active/prepared operation needs them. Inspect resolved paths
within the configured publication root. There is no automatic age-based deletion policy in v0.1.

## Tests and maintenance

PostgreSQL tests create a unique `portco_test_<uuid>` database and drop only that database. Set
`PORTCO_TEST_POSTGRES_ALLOW_CREATE=1` and `PORTCO_TEST_POSTGRES_URL` to a dedicated test server whose
user has CREATE DATABASE permission. Tests never reset the URL's existing database/schema.

Run `uv run python scripts/release_evidence.py` for a synthetic evidence and SQLite recovery rehearsal.
Review dependencies monthly or before sharing a new release; rerun CI, eval, minimal wheel and container
checks after updates. Keep judge API calls off unless an explicit experiment and spending limit exist.
Track external model/runtime support separately; avoid silently upgrading optional tooling into the
working application environment.
