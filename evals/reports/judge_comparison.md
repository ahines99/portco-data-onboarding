# Judge vs deterministic baseline

Generated 2026-09-23T16:07:32+00:00 in `replay` mode.

> Run in **replay** mode: without recorded cassettes the judge abstains everywhere, so this report shows the no-regression path only. Record a live comparison with `PORTCO_ANTHROPIC_API_KEY=... python -m evals.judge_eval --mode record`.

| fixture | baseline top-1 | judge top-1 | consulted | applied | abstained | baseline calibration | judge calibration | judge cost |
|---|---|---|---|---|---|---|---|---|
| portco_a | 1.000 | 1.000 | 1 | 0 | 1 | {'high': 1.0, 'low': 1.0} | {'high': 1.0, 'low': 1.0} | $0.0000 |
| portco_b | 1.000 | 1.000 | 4 | 0 | 4 | {'high': 1.0, 'low': 0.5, 'medium': 1.0} | {'high': 1.0, 'low': 0.5, 'medium': 1.0} | $0.0000 |

**Decision:** KEEP OPT-IN (no measured improvement over the deterministic baseline). The judge may only reorder deterministic candidates or abstain; it never clears review and never raises confidence above MEDIUM, so enabling it cannot bypass a human gate.
