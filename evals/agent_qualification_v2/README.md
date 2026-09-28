# Agent-authored qualification corpus v2

Six new synthetic cases were authored in a separate agent context using public ontology and
contracts, before any inference was run. The author did not inspect the mapper/scoring implementation,
old labels or old benchmark results. [Provenance](PROVENANCE.json) states the consulted files and
limitations. This is separate-agent authorship within the same project session, not external human
evaluation, customer data or a statistically representative sample.

The corpus has 11 tables, 62 labelled columns and 34 rows. It tests unfamiliar billing terminology,
recurring-payment units, coincidental key overlap, signed ledger amounts, ambiguous compensation
and unsupported operational entities. Some source-owner semantics exist only in SQL comments;
those expectations can expose a metadata limitation without establishing that inference could
recover an unknowable meaning.

The frozen manifest SHA-256 is
`e21b4cf4a8b2ad802c9cdbfb884c94ab1e42c92a1753b67275d2fd8eac078647`.
The manifest covers input SQL, labels and provenance. Do not rewrite frozen files to improve a
score. `README.md` is post-evaluation commentary and is not part of the frozen corpus.

```text
uv run python -m evals.unfamiliar_benchmark --corpus evals/agent_qualification_v2 --manifest-sha256 e21b4cf4a8b2ad802c9cdbfb884c94ab1e42c92a1753b67275d2fd8eac078647 --output var/agent-qualification-v2.json --enforce-safety
```

The evaluator requires an explicitly supplied freeze hash for a non-default corpus. Each inference
worker receives an input copy and blocks Python-level reads of the selected label directory; the
evaluator reads labels after the worker exits. This is a regression guard, not an OS sandbox.

| Measurement | First run | After remediation |
| --- | ---: | ---: |
| Correct mappings / proposals | 42 / 52 | 42 / 52 |
| Positive targets covered | 42 / 43 | 42 / 43 |
| Correct entity decisions | 10 / 11 | 10 / 11 |
| Correct / expected joins | 3 / 3 | 3 / 3 |
| Correct / expected units | 7 / 7 | 7 / 7 |
| Proposals requiring review | 22 / 52 | 48 / 52 |
| Unresolved fields | 10 | 10 |
| Safety gate | Fail | Pass |

The first run surfaced an unreviewed currency mapping in an unsupported table classified with
uncertain entity confidence. The general repair propagates entity uncertainty to every dependent
column proposal; an exact field-name match cannot settle whether the containing entity is correct.
Mapping accuracy did not improve. Review burden increased substantially, and all ten incorrect
proposals remain errors even though they are now review-bound.

The [first report](../../docs/evidence/agent-qualification-v2-first.json) is preserved byte-for-byte
(SHA-256 `c00b43c661b977c43c88c6f8ad947f4b67390cb6601d5b2ab2ec6b84fe0c4969`).
The [remediation report](../../docs/evidence/agent-qualification-v2-remediation.json) is explicitly
feedback-informed. Reports include inference-source hashes because implementation changes can
precede their final commit. Subsequent runs are regression evidence, not untouched held-out tests.
The different v1 corpus and original 0/10 probe remain separate experiments.
