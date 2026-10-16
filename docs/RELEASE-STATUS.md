# Release status

Updated 2026-10-16. This page identifies what has actually shipped; older acceptance records are historical evidence.

| Item | Status |
|---|---|
| October candidate | [v0.2.0-rc.4](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.2.0-rc.4): release notes, source archive, wheel and verification manifest |
| October remediation | [Merged into main](https://github.com/ahines99/portco-data-onboarding/pull/1); publication is gated on the exact release commit's hosted checks |
| Historical stable tag | [v0.1.1](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.1.1); also predates the October fixes |
| rc.3 source archive | Packaging-only correction; use the [release's current checksums](https://github.com/ahines99/portco-data-onboarding/releases/download/v0.2.0-rc.3/SHA256SUMS.txt). rc.3 application code still predates the October fixes |
| Supported execution | Local and CI; the [project page](https://ahines99.github.io/portco-data-onboarding/) is a static replay |

## What changed

The [October audit](AUDIT-2026-10-10.md) found 23 numbered defects, including a revenue classification that produced zero revenue while every check passed. The [remediation ledger](REMEDIATION-2026-10-11.md) maps fixes to regression tests. The follow-up also fixes shared workflow-cache races, forwards cancellation into worker loops and terminates cancelled dbt processes.

Distribution rules now exclude local `/.config/` data. The rc.3 correction removes only `.config/auth0/config.json` from the original archive; it does not retag or substitute new application code. All 429 retained archive entries are verified unchanged. The original file held development metadata, not tokens or secrets. Its release notes disclose the packaging correction; the rc.4 manifest records the old and corrected archive hashes.

Frozen audit evidence retains its original bytes. Fresh Git commit/clone tests check all 33 manifest hashes with and without automatic line-ending conversion.

## Verification

The attached [rc.4 verification manifest](https://github.com/ahines99/portco-data-onboarding/releases/download/v0.2.0-rc.4/verification.json) identifies the exact source commit, hosted CI run, job results, package hashes and rc.3 correction. [SHA256SUMS.txt](https://github.com/ahines99/portco-data-onboarding/releases/download/v0.2.0-rc.4/SHA256SUMS.txt) covers every rc.4 asset except itself. Later documentation commits do not move the release tag.

Publication requires all 11 verification jobs to pass: lint/types, the general suite and reference-calculator coverage, security, PostgreSQL, golden evaluations and frozen safety checks, the demo, Linux and Windows packaging, container runtime restrictions and non-default `PORT`, production entry-point startup/shutdown/restart, and dependency auditing. The publisher then downloads both releases again and verifies every asset against its checksums. These are reproducible CI checks, not production deployment acceptance.

The first publication attempt stopped before uploading because `uv build` added a `.gitignore` marker beside its packages. [The follow-up](https://github.com/ahines99/portco-data-onboarding/pull/6) handles that marker, adds regression coverage and was also checked through a real package build. Unexpected release files remain errors.

The refreshed scripted demo is recorded after the implementation commit and identifies that commit in [its provenance](evidence/demo-replay.json). It has 28 review items and 27/27 reconciliation checks. Reviewer decisions are scripted; this is not a human usability study.

## Scope and limitations

Supported inputs are synthetic fixtures, explicit [CSV snapshots](CSV-SOURCE.md) and bounded read-only [PostgreSQL snapshots](POSTGRES-SOURCE.md). Certification applies to the reviewed source, relationships, transforms and supported metrics. Unknown semantics remain review work.

The frozen v1 and v2 safety results are post-remediation observations, not fresh independent validation. The earlier 0/10 probe, remaining incorrect proposals and other constraints are explained in [evaluation and limitations](EVALUATION.md). Full MetricFlow support, independent usability, customer savings and accepted live hosting remain unclaimed. Container scan results may retain unfixed upstream vulnerabilities even when the fixable HIGH/CRITICAL gate passes.

Deferred engineering work: a fresh frozen source-family corpus, stateful workflow property testing, reconciliation streaming and memory measurements at the 250,000-row bound, and GL currency contracts.

## Reading path

[Project page](https://ahines99.github.io/portco-data-onboarding/) → [case study](portfolio_case_study.md) → [architecture](architecture.md) → [evaluation and limitations](EVALUATION.md) → release status.

Historical acceptance and planning are in [the archive](archive/README.md). Exact prior release checks and assets remain attached to their [GitHub releases](https://github.com/ahines99/portco-data-onboarding/releases).
