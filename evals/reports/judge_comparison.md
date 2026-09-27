# Judge vs deterministic baseline

Generated 2026-09-27T20:50:18+00:00 in `replay` mode.

> Run in **replay** mode: without recorded cassettes the judge abstains everywhere, so this report shows the no-regression path only. Record a live comparison with `PORTCO_ANTHROPIC_API_KEY=... python -m evals.judge_eval --mode record`.

| fixture | baseline top-1 | judge top-1 | consulted | applied | abstained | baseline calibration | judge calibration | judge cost |
|---|---|---|---|---|---|---|---|---|
| portco_a | 1.000 | 1.000 | 1 | 0 | 1 | {'high': 1.0, 'low': 1.0} | {'high': 1.0, 'low': 1.0} | $0.0000 |
| portco_b | 0.971 | 0.971 | 4 | 0 | 4 | {'high': 1.0, 'low': 0.5, 'medium': 1.0} | {'high': 1.0, 'low': 0.5, 'medium': 1.0} | $0.0000 |
| heldout_challenges | 0.500 | 0.500 | 4 | 0 | 4 | {'medium': 0.5, 'low': 0.5} | {'medium': 0.5, 'low': 0.5} | $0.0000 |

Fixture accuracy/calibration covers labeled columns only; it is not whole-output precision. portco_a: {'labeled_columns': 68, 'proposals': 68, 'labeled_proposal_fraction': 1.0, 'unlabeled_proposals': []}; portco_b: {'labeled_columns': 35, 'proposals': 35, 'labeled_proposal_fraction': 1.0, 'unlabeled_proposals': []}
Held-out rows test reranking using fixed baseline-confidence cohorts; fixtures report output-confidence buckets. The rule permits equality on saturated fixtures, requires >= 1 percentage point improvement elsewhere, and rejects regression in any populated confidence bucket. Default configuration remains disabled.

**Decision:** KEEP OPT-IN (no accuracy improvement of at least one percentage point). The judge may only reorder deterministic candidates or abstain; it never clears review and never raises confidence above MEDIUM, so it cannot bypass a human gate.
