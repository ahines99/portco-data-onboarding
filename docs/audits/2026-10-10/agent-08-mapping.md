# Agent 08 — mapping, entity and join inference audit

Audit date: 2026-10-10. Read-only source audit against commit `e1f8e36936f832b019dbd9418994ea95dc47f7a5`. No tracked files changed; no paid model calls; frozen input/label files untouched. Two pinned benchmark runs and focused temporary-DuckDB reproductions completed.

Standalone reproduction: `.venv/Scripts/python.exe var/audit-2026-10-10/agent-08-probe.py`. The script locates the repository from its own path, uses isolated temporary state, disables inherited project/model/database configuration, and writes `agent-08-probe-results.json` under this audit directory. Verified once from working directory `D:\` with exit 0: both defects reproduced, and customer ID 1 was incorrectly excluded. The script uses pure simulated review decisions without recording approvals, publishing, or calling a model.

## Executive assessment

The deterministic mapping path is conservative about uncertain entities, monetary fields, transforms and PII. Frozen safety gates pass, but the newly reproduced generic-surrogate-key join defect can silently affect generated customer rows. Safety should be strengthened at relationship inference before attempting to lower review thresholds. Current v2 accuracy and review burden do not establish scalable unfamiliar-source onboarding: 42/52 proposals are correct and 48/52 require review.

## P1 — unrelated generic primary keys become automatic joins and filter valid customer rows

**Observed:** `src/services/joins.py:42` gives identical column names full name support. Lines 83–93 permit a table's own primary key when both columns share a name, and do not classify that pair as structural. Lines 111–123 give full-containment pairs score 1.0/HIGH without considering entity uncertainty or requiring an ontology relationship. Ambiguity abstention at lines 165–170 applies only when at least one contender is structural.

Focused end-to-end inference used independent `raw.customers(id, customer_name, currency)` and `raw.vendors(id, vendor_name)` tables, each with IDs 1, 2, 3. Entity classifications were customer LOW/.5125 and vendor MEDIUM/.55. Both `customers.id -> vendors.id` and the reverse were HIGH/1.0, `requires_review=false`, no reason codes. Evidence: `generic-id-join-repro.json`.

**Verified downstream:** added a normal vendor soft-delete flag marking only vendor 1 deleted. Pure `gates.resolve` was supplied simulated APPROVE decisions for the actual mapping/filter review items, with **no join decisions**. Both inferred joins survived because `src/services/gates.py:167` retains joins that do not require review. Generated SQL was executed against the synthetic source in a temporary DuckDB, without actual approval-store writes or publication. `Generator.build_intermediate`, `src/services/generation.py:305`, builds cross-entity scope dependencies from these joins; cycle breaking removes one direction. Resulting customer intermediate SQL joins vendor_id to customer_id and propagates the vendor exclusion. `dim_customer` contains only Beta/2 and Gamma/3: valid Acme/1 is lost solely because unrelated vendor/1 was deleted. Full input SQL, assignments, simulated decision keys, generated SQL and result rows: `generic-id-scope-impact.json`.

**Fix:** do not auto-trust generic same-name PK-to-PK relationships. Require explicit field/relationship evidence, or flag them for review; propagate endpoint entity uncertainty to every dependent join. Evaluate ambiguity for all competing keys, including exact lexical matches. Neither shared integer domain nor 100% containment identifies business meaning.

**Tests:** unrelated customer/vendor surrogate keys; generic keys across three target tables with equal scores; canonical keys on uncertain entities; and an end-to-end deletion-scope test proving a vendor filter cannot remove customer rows without a reviewed legitimate relationship. Keep existing known FK and overlap regressions.

## P2 — optional judge reranking leaves target-specific metadata stale

**Observed:** `src/services/mapping.py:474` / update at line 493 replaces the canonical field but preserves the old score, transform, PII handling and reason codes. Target-dependent metadata was computed before judging at lines 227–255. An allowed-choice offline stub changing `customer.customer_name` to `customer.billing_email` keeps `pii_handling=None`, old score .54 rather than the selected alternate's .42, and omits `PII_FIELD`, despite the ontology declaring email PII. Reproduction: `judge-stale-metadata-repro.json`.

The same state-copy design can retain an inappropriate `cents_to_major` or mixed-date transform when a different kind of target is selected. This latter transform scenario is a code-path inference, not a separately executed reproduction. `gates.py:127` uses the proposal defaults on ordinary approval, and `generation.py:123` hashes only explicit `pii_handling == 'hash'`. Thus stale metadata can survive a reviewer's ordinary approval. Review remains mandatory, the judge is disabled by default, and this is **not** evidence of a human-gate bypass or a live data disclosure.

**Fix:** use a shared target-finalization routine after deterministic assignment and judge selection. Recompute type compatibility, target PII/metric status, valid transform, selected score and explanation; preserve all source-derived safety constraints. Reject incompatible target/transform combinations at resolution as a second boundary. Add allowed reranks into/out of PII targets and between financial, date and identifier targets. The judge comparison in `evals/reports/judge_comparison.md` is replay-only and shows no accuracy gain; keep opt-in until a separately authorized, properly attributed study demonstrates value.

## Fresh frozen benchmark results

Commands used the existing `.venv/Scripts/python.exe`, `--enforce-safety`, the built-in v1 pin `2610a148aaa31dd01cb842acdd5233405e4925025f29a98e13fd3b7dfa364fd0`, and explicit v2 pin `e21b4cf4a8b2ad802c9cdbfb884c94ab1e42c92a1753b67275d2fd8eac078647`. Both exited 0.

| Measurement | v1, four cases | v2, six cases |
|---|---:|---:|
| Correct mappings / proposals | 32/33, 96.97% | 42/52, 80.77% |
| Correct / positive labeled targets | 32/32 | 42/43 |
| Entity decisions correct | 10/10 | 10/11 |
| Correct/proposed/expected joins | 3/3/3 | 3/3/3 |
| Correct/attempted/expected units | 6/6/6 | 7/7/7 |
| Mapping proposals requiring review | 17/33, 51.52% | 48/52, 92.31% |
| Unresolved labeled fields | 8 | 10 |
| Correct abstentions on ambiguous fields | 8/9 | 10/19 |
| Frozen safety gate | PASS | PASS |

Artifacts: `frozen-v1.json`, `frozen-v2.json`. Review fractions count mapping proposals, not review duration or all gate items; unresolved fields are a separate burden. v1's sole erroneous proposal is `batch_marker -> invoice.status`. v2 includes `trading_style -> customer.billing_email`, `compensation_basis -> employee.national_id`, `net_movement -> gl_entry.debit_amount`, and five wrong mappings from unsupported operational `raw.accounts`. All measured errors require review. Routing errors to review fixes measured safety, not accuracy.

The docs accurately disclose the limits: v2 has only 11 tables, 62 labeled columns and 34 rows; separate-agent authorship is not external human qualification; remediation is feedback-informed (`evals/agent_qualification_v2/README.md:6`, `:9`, `:42`, `:48`). Current reruns are regression evidence, not untouched holdout results. The new generic-key case demonstrates a material blind spot despite green safety gates.

## Improvement plan that preserves safety

1. Fix join semantics and rerank metadata before lowering review rates. Add generic local surrogate-key collisions to a new versioned adversarial corpus rather than modifying frozen labels. Track both proposal-level and final generated-data errors.
2. Improve review efficiency by addressing shared causes: show uncertain entity decisions and all dependent field/join impacts together; collect trusted source-owner meaning, currency scale, cadence and key relationships once per source. Preserve explicit approval scope and hash binding. Source values alone cannot establish whether net amounts are debit amounts or compensation is annual salary.
3. Add abstention and candidate-margin features to mapping assignment. The current greedy assignment iterates lower-scoring alternatives when a target is occupied (`mapping.py:179`); it can turn weak lexical evidence into semantically implausible mappings. Measure alternatives using precision, positive-target recall, abstention correctness, review items and reviewer time together. Do not optimize the raw number of review flags.
4. Keep heuristic score and empirical reliability separate. Current scores are weighted similarities, not probabilities; `unfamiliar_benchmark.py:264` says so correctly. Build risk-versus-coverage curves on genuinely fresh source-system cohorts, and only consider auto-acceptance expansion for stable, low-risk field classes. Retain mandatory review for PII, financial meaning, transforms and unresolved entity/join uncertainty. Selective prediction research provides the risk/coverage framework, but its statistical guarantees do not automatically apply to this small hand-authored, correlated corpus. [Geifman and El-Yaniv, Selective Classification for Deep Neural Networks](https://arxiv.org/abs/1705.08500).
5. Separate regression, development and fresh qualification sets; rotate future cohorts by ERP/vendor/source system and ontology ambiguity. Preserve failed first-run reports and predeclare success criteria. Repeated feedback-informed reuse can overfit evaluation even when labels are frozen. [Dwork et al., Generalization in Adaptive Data Analysis and Holdout Reuse](https://proceedings.neurips.cc/paper_files/paper/2015/file/bad5f33780c42f2588878a9d07405083-Paper.pdf).
6. For performance, profile repeated ontology lookups and pairwise containment on wide schemas. `field_owner` rebuilds synonym ownership and the global field set (`entities.py:35`), repeatedly inside scoring loops; precompute immutable indices per loaded ontology. Join enumeration performs containment per candidate table/column pair; prune using semantic relationship/key evidence and batch compatible containment work. These are code-based candidates, not measured speedup claims.

## Additional evaluator limits for follow-up

`unfamiliar_benchmark.py:111` normalizes joins as unordered endpoint pairs, so endpoint-direction or cardinality mistakes are not independently scored. `:268` explicitly has no accuracy floor. Do not interpret safety PASS as high utility or semantic equivalence of generated SQL; add directed/cardinality and output-scope assertions in future evaluation. Generic gate enforcement is assigned to another audit agent; this report does not duplicate that review.

## Strengths

Frozen pins fail closed; worker labels are separated with an honestly documented Python regression guard; reports retain source hashes; PII and monetary transformations are review-bound; uncertain entity confidence now propagates through field proposals; high-risk financial column competition remains visible; live model usage is optional and replay abstains safely without cassettes. Existing documentation is unusually clear about measured failures and the increase in review burden.
