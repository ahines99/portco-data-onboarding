# Final three-agent audit closeout — v0.1.1

The 2026-09-27 audit reviewed functionality, security/release integrity, and portfolio/evidence
independently against `db34e45645f7c386c04c6decdc0607e995ac7ca8`. It reproduced defects despite
the earlier passing CI and owner acceptance. Version 0.1.1 addresses every required finding.

| Finding | Resolution | Regression evidence |
|---|---|---|
| P1: CLI ignored exported run/gate/hash; mapping MCP route could approve current certification content | Require caller-observed metadata; validate CLI run/gate; restrict mapping tool to mapping/test-failure gates; certify through dedicated route; reload and lock current state inside approval transaction | `tests/test_review_binding.py`: stale/changed packet, missing/mismatched CLI metadata, certification bypass, actual concurrent SQLite/PostgreSQL packet update; MCP schema/route tests |
| P2: 99.9% invoice match threshold permitted one arbitrarily large discrepancy | Every invoice header must equal its line sum; unknown totals fail; report counts and maximum absolute discrepancy without source identifiers | `tests/test_invoice_consistency.py`: large populations, penny and $100 differences, offsetting discrepancies, unknown totals, full workflow blocked at test-failure review |
| P2: Re-scoring relabeled assistant annotations as human review | Validate annotation method and scope; preserve owner approval basis and non-exhaustive/non-independent qualifications | `tests/test_skill_comparison.py`: CLI round-trip against committed study; invalid/contradictory provenance rejected; counts remain 3/3 |
| P2/P3: Active documents contradicted completed study and overstated unfamiliar-schema support | Synchronize accepted study status and narrow README/site pitch to supported synthetic schemas; expose 0/10 unfamiliar-schema result beside the introduction | Local links and headless desktop/mobile browser QA; original transcripts and historical acceptance retained |
| Verification follow-up: Windows path spellings caused a false containment rejection during concurrent publication | Normalize equivalent resolved Windows extended-path prefixes before containment comparison; retain traversal and symlink rejection | Publication recovery suite plus deterministic extended drive/UNC path regressions and repeated concurrent publication |
| Maintenance: Container scan did not enforce severity | Retain unfiltered Trivy JSON; separate gate rejects fixable HIGH/CRITICAL findings using the same database | Hosted `container-smoke` job executes both scans and always uploads the complete report |

## Verification and release

The release requires lint/format/type checks, the non-PostgreSQL suite, all 37 golden evaluation
cases, base-only sdist/wheel installation and demonstrations, browser QA, and all ten hosted CI jobs.
Hosted verification includes the PostgreSQL concurrency regression, Linux/Windows installed-package
smoke tests, actual container publication/recreation, application dependency scan, and the image gate.
The [v0.1.1 release](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.1.1)
records the exact source SHA, passing CI run, distribution checksums and final observed results.

Client migration: `submit_mapping_review` now requires the observed `subject_hash` and `gate`
alongside `run_id` and decisions. Only `mapping_review` and `test_failures` are accepted. CLI review
files require all exported packet metadata. Re-export and review changed packets; do not replace
an old hash with the current one without reviewing the current contents.

## What complete means here

This is a finished, reproducible synthetic-data portfolio within its declared scope. It does not
establish arbitrary-schema onboarding or production deployment readiness. The held-out probe
returned 0/10 matches; full MetricFlow runtime support and optional paid judging remain deferred;
the six live sessions do not establish Skill efficacy; static development authentication and
unfixed upstream OS vulnerabilities remain documented deployment boundaries. No customer impact,
independent human study, or new personal owner review is claimed by this patch.

The v0.1.0 tag, original six model transcripts and delegated acceptance record remain historical
evidence. This patch changes the implementation and reproducible score metadata, not those events.
