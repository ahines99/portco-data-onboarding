# Profiling thresholds (from ontology/scoring.yaml)

| Setting | Value | Used for |
|---|---|---|
| `profiling.stale_after_days` | 35 | `STALE_DATA` on fact tables, measured against the source as-of date |
| `profiling.minor_units_ratio` | 20 | `POSSIBLE_MINOR_UNITS`: integer money column mean / median of decimal money means |
| `profiling.duplicate_name_ratio` | 0.01 | `DUPLICATE_ENTITIES`: share of names colliding after case/punctuation normalization |
| `profiling.low_cardinality_max` | 12 | Category columns whose labels may be returned (only after PII and injection checks) |
| `confidence.high` / `.medium` | 0.80 / 0.55 | Score bands for entities, joins and mappings |
| `join.review_containment_below` | 0.98 | Joins with orphans go to review |

These are deterministic. If a finding looks wrong, say which threshold produced it and let the
reviewer judge; do not second-guess the arithmetic.
