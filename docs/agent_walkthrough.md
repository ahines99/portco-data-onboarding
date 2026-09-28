# Driving a run from Claude Code (MCP + Skills)

This walkthrough connects Claude Code to the MCP server and lets the agent drive onboarding while a
human reviews at each gate.

## 1. Connect

The repository ships `.mcp.json`. It starts the server over stdio as the principal `agent:claude-code`
with the **agent** role. That principal can start and resume runs and read every resource, but it
cannot approve, certify or waive anything.

```bash
uv sync --all-extras
uv run poe fixtures
claude            # from the repo root; approve the project MCP server when prompted
```

Make the Skills available to Claude Code by copying or linking them into the project skills folder:

```bash
mkdir -p .claude/skills && cp -r skills/* .claude/skills/        # or symlink on macOS/Linux
```

## 2. Scripted scenario

| Step | Who | Action |
|---|---|---|
| 1 | Agent | Prompt `onboarding_kickoff` with `fixture:portco_a`. The agent calls `start_onboarding_run` and reads `run://{run_id}/profile` and `run://{run_id}/findings` (schema-profiling Skill). |
| 2 | Agent | Explains the 22 pending items using the canonical-pe-ontology Skill: `UNIT_MISMATCH` on invoice lines, `SEMANTIC_TRAP` on `rev`, the orphaned CRM join, and the PII handling. |
| 3 | Agent | Tries `submit_mapping_review` and gets `FORBIDDEN`. It tells the human what to decide instead. |
| 4 | Human | `uv run portco review <run_id> --export review.yaml`, inspects every item and fills its decision, then `uv run portco review <run_id> --import review.yaml --reviewer alex`. `rev` is already proposed as `amount`: approving it is not an override. The command prints the approval id. |
| 5 | Agent | `generate_dbt_artifacts(run_id, approval_id)`, then `run_sandbox_tests`. It reports reconciliation results with the dbt-modeling and data-quality Skills. |
| 6 | Human | Certifies: `portco review <run_id> --export cert.yaml`, sets decisions, and imports the file. Or a reviewer-scoped MCP client calls `certify_run`. |
| 7 | Agent | `publish_run(run_id, certification_id)`, then reads `run://{run_id}/summary`. |

## 3. What is automated in CI

Eval case **G31** runs exactly this tool sequence through the in-process MCP client, with the reviewer
steps performed by a reviewer principal. It asserts tool order, schema-valid arguments, the agent's
`FORBIDDEN` self-approval, and completion. Excerpt of its recorded trace:

```text
start_onboarding_run      agent     ok
list_pending_reviews      agent     ok
submit_mapping_review     agent     FORBIDDEN
submit_mapping_review     reviewer  ok
generate_dbt_artifacts    agent     ok
run_sandbox_tests         agent     ok
get_run_status            agent     ok
certify_run               reviewer  ok
publish_run               agent     ok
```

## 4. With-Skill vs without-Skill comparison

[Six real Claude Code sessions](evidence/live-study/README.md) completed the three-prompt comparison
on 2026-09-27. All six stopped for mapping review during collection. One run was subsequently
certified and published under [explicit owner delegation](FINAL-ACCEPTANCE.md); that continuation is
separate from the experiment and does not rewrite its transcripts.

The owner-approved assistant annotations count three findings without Skills and three with Skills.
Only one session invoked a Skill body. This is a non-exhaustive review, not independent blinded
annotation or evidence of general improvement. The malformed-fixture sessions stopped before sandbox
execution and therefore do not demonstrate model discovery of the injected test failures.

To repeat the study, follow [the six-session protocol](skill_comparison.md). Each pair uses fresh
state and identical prompts, model settings and MCP permissions, with project Skills available only
in the `with` condition. `scripts/compare_skills.py prepare` creates the manifest; `score` validates
paired settings, line-anchored findings and declared annotation provenance. Static checks in
`tests/test_skills.py` separately verify tool, resource and prompt references against the live server.
