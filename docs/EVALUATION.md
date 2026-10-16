# Evaluation and limitations

[Project page](https://ahines99.github.io/portco-data-onboarding/) →
[Case study](portfolio_case_study.md) → [Architecture](architecture.md) →
**Evaluation and limitations** → [Release status](RELEASE-STATUS.md)

The evidence answers different questions: supported fixtures exercise the complete financial
workflow, unfamiliar schemas test mapping and review boundaries, and source exercises test
ingestion. Their populations overlap and should not be combined into one accuracy or test count.
Use [release status](RELEASE-STATUS.md) for the exact source revision, CI and release assets.

## Financial and workflow correctness

The synthetic SaaS demonstration generates nine metrics: active customers, ARR, billings, COGS,
EBITDA, gross margin, MRR, OPEX and recognized revenue. Generated SQL and semantic definitions
execute in a disposable sandbox; monetary results must match reference calculations to the cent.
The [current transcript](evidence/demo-transcript.txt) records the check and review populations.
The [evidence index](evidence/README.md) links the reports, manifests and recovery verification.

The [October audit](AUDIT-2026-10-10.md) found 23 numbered findings despite the previous passing
suite. Its clearest counterexample was `Revenue`: a noncanonical category made both implementations
omit a 100.00 credit and agree on zero revenue. [Remediation](REMEDIATION-2026-10-11.md) adds
executable category constraints, independent domain checks and regressions for the reproduced defects.
Agreement between two calculators is insufficient when both share an unchecked semantic assumption.

## Unfamiliar-schema results

| Experiment | Observed result | Interpretation |
|---|---|---|
| [Original probe](evidence/heldout-probe.json) | Zero proposals; 0/10 labeled targets matched; never approved or published | Supported-fixture accuracy did not generalize to this schema. |
| [V1 first post-change run](evidence/unfamiliar-benchmark-first-postchange.json) | 31/33 correct proposals; 31/32 positive targets; safety failed | Accuracy was unchanged from the reconstructed baseline; competing monetary meanings bypassed review. |
| [V1 first remediation](evidence/unfamiliar-benchmark.json) | 32/33 correct proposals; 32/32 targets; 7/33 reviewed; safety passed | One wrong reviewed proposal and eight unresolved opaque fields remained. |
| [V1 rc.3 regression](evidence/unfamiliar-benchmark-rc3.json) | Same 32/33 accuracy and 32/32 coverage; 17/33 reviewed; safety passed | The later uncertainty repair increased review effort. |
| [V2 first run](evidence/agent-qualification-v2-first.json) | 42/52 correct proposals; 42/43 targets; 22/52 reviewed; safety failed | Exact column matches bypassed uncertain table-entity interpretation. |
| [V2 remediation](evidence/agent-qualification-v2-remediation.json) | Same accuracy/coverage; 48/52 reviewed; safety passed | Ten incorrect proposals and ten unresolved fields remain. Review coverage improved; mapping accuracy did not. |

The [v1](../evals/unfamiliar/README.md) and [v2](../evals/agent_qualification_v2/README.md)
corpora were authored by separate agents and frozen before their first evaluations. Repairs use
feedback from those evaluations; subsequent runs are regressions, not untouched held-out results.
Agent authorship is not external human validation. The original failed reports remain available.

## Source and reviewer evidence

| Exercise | What it shows | What it does not establish |
|---|---|---|
| [Typed CSV smoke](evidence/csv-source-smoke.json) | 11 synthetic tables / 14,639 rows, restarts and nine-metric publication | Continuous synchronization or arbitrary customer schemas |
| [PostgreSQL acceptance](evidence/postgres-source-acceptance.json) | Read-only extraction of 11 synthetic tables / 14,639 rows, nine metrics, 59 published files, 45 audit events and zero waivers | Customer-system access or production deployment; review was scripted |
| [Public retail exercise](PUBLIC-OPERATING-DATA.md) | 10,000 real historical rows imported/profiled; six aggregate controls | Approved financial mappings, certification or business benefit |
| [Separate operator/reviewer agents](evidence/agent-reviewer-qualification/README.md) | Six SAP-style metrics, 38 publication files, 46 audit events; misleading status mapping explicitly rejected | Blinded review or human usability; the reviewer inspected source and answer-key entries |
| [Six real model sessions](evidence/live-study/README.md) | Actual MCP integration, three paired prompts, one Skill-body invocation | General Skill efficacy; owner-approved assistant annotations are non-exhaustive and not independently blinded |

The [human operator pilot](OPERATOR-PILOT.md) is a protocol, not a completed study.
Machine/agent execution durations exclude human waiting and do not measure analyst savings.

## Operational boundaries

- Publication targets a versioned local directory. Warehouse deployment would require its own
  environment-scoped approval and acceptance.
- Local reviewer identities trust the OS operator. Control of the process or state database is
  outside the agent-role boundary.
- Production JWT verification and deployment controls are implemented; a live hosted backend,
  reviewer identity integration and hosting recovery have not received end-to-end acceptance.
- PostgreSQL, production-smoke and container checks have separate CI populations. A historical
  green run proves its tested revision only; follow the current release's exact CI links.
- The local semantic executor supports a bounded monthly subset. MetricFlow 0.15.0 configuration
  validation failed in the [compatibility experiment](metricflow-investigation.md).
- The optional LLM judge defaults off until a recorded live comparison demonstrates improvement
  over deterministic ranking. See [ADR-0010](adr/0010-llm-mapping-judge.md).
- There are no production customers, measured savings, investment-performance outcomes or
  independent first-use usability results.

The remaining engineering work includes fresh source-family evaluation, reconciliation memory
measurement at the extraction bound and explicit GL currency contracts. See the remediation
record and release status for the current disposition rather than historical planning checklists.
