# Frozen unfamiliar-schema benchmark v1

These four synthetic cases were authored by a separate agent that inspected the public
contracts and ontology, but not mapper/scoring implementation, previous probe labels, or
the mapper agent's implementation plan. Inputs and labels were frozen before mapper edits.
This is independent **agent authorship**, not external human evaluation or fully blinded
research. The cases are public and small; later tuning against them invalidates held-out claims.

`inputs/` contains only source-building SQL. `labels/` is the evaluator answer key.
The manifest fixes both by SHA-256. Changing cases requires a new version, not refreshing
the stored digest. The inference worker receives a temporary SQL copy, runs without an LLM,
and stops after canonical mapping. It neither approves nor publishes anything. A Python
audit hook rejects reads under the labels directory. This is a regression guard, **not an
operating-system sandbox** or a guarantee against malicious inference code.

Run from the repository root:

```powershell
uv run python -m evals.unfamiliar_benchmark --output var/unfamiliar-benchmark.json
uv run python -m evals.unfamiliar_benchmark --enforce-safety --output var/unfamiliar-benchmark.json
```

The first command always reports accuracy without an arbitrary pass floor. The second also
exits unsuccessfully for changed source data, broken inference separation, duplicate source
proposals, incorrect unreviewed mappings/units/joins, or incorrect high-confidence entities.
Correct but ambiguous representations identified in advance must be reviewed or omitted.
Failures are evidence, not a reason to change the frozen labels.

Measurements cover entity correctness (including explicit no-match entities), mapping
precision and recall, coverage, joins, monetary transforms, abstentions, and review burden.
Null precision means no proposals, never perfect accuracy. Null mapping labels mean no
uniquely defensible canonical target. Missing expected entities do not count as correct
abstentions. Wrong proposals can be safely surfaced for review but still count as errors.
Review burden is a count/rate, not measured reviewer time. Low/medium/high confidence
bins report observed correctness; heuristic scores are not calibrated probabilities.

The benchmark includes unfamiliar table naming, wholly opaque semantics, coincidental key
overlap with orphans, duplicated monetary representations, and pipeline/billing distinctions.
Some source fields remain recognizable deliberately: these cases separate structural
recognition, semantic impossibility, relationship noise, and units rather than claim every
input is opaque. Tiny deterministic samples cannot establish customer-system generalization.

The baseline is `docs/evidence/unfamiliar-benchmark-baseline.json`; subsequent results should
be separate files. Reports record commit and inference-source hashes because a working-tree
evaluation may precede its final commit. The original unfamiliar-schema probe remains intact.
The finalized baseline was reconstructed from an isolated archive of original commit
`e09be37f9e99f6c805698af50b3d13b5f421a923` after concurrent implementation began, using
the frozen cases and the same Python environment. Shared implementation files were not reset.

## Recorded results

| Measurement | Original baseline | First post-change | Post-benchmark remediation |
| --- | ---: | ---: | ---: |
| Correct mappings / proposals | 31 / 33 | 31 / 33 | 32 / 33 |
| Mapping precision | 93.94% | 93.94% | 96.97% |
| Recall over 32 positive labels | 96.88% | 96.88% | 100% |
| Correct entity decisions | 10 / 10 | 10 / 10 | 10 / 10 |
| Correct / expected joins | 3 / 3 | 3 / 3 | 3 / 3 |
| Correct / expected units | 5 / 6 | 5 / 6 | 6 / 6 |
| Proposals requiring review | 6 / 33 | 6 / 33 | 7 / 33 |
| Unresolved fields | 8 | 8 | 8 |
| Safety gate | Fail | Fail | Pass |

Entity correctness includes two explicit ambiguity abstentions. Eight fully opaque fields
remain unmapped. A noncanonical operational field still receives an incorrect, review-required
proposal, which counts against precision. The independent first post-change run showed no
improvement; it exposed an unreviewed monetary interpretation among competing representations.
The resulting generic failure disclosure informed a monetary-ambiguity fix. Therefore the
final result is **post-benchmark remediation**, not untouched held-out evidence. Inputs and
labels remained unchanged, and the original baseline and first post-change reports are
preserved byte-for-byte. Review burden increased from 18.18% to 21.21% of proposals.

Reports are in `docs/evidence/unfamiliar-benchmark-baseline.json`,
`docs/evidence/unfamiliar-benchmark-first-postchange.json`, and
`docs/evidence/unfamiliar-benchmark.json`. Passing the final safety gate proves only these
small frozen cases satisfy the measured controls; it does not prove generalization, customer
impact, production readiness, or probabilistic uncertainty calibration.
