# Release status

Updated 2026-10-16. This page identifies what has actually shipped; older acceptance records are historical evidence.

| Item | Status |
|---|---|
| Latest published candidate | [v0.2.0-rc.3](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.2.0-rc.3); it predates the October fixes |
| October remediation | Preparing **v0.2.0-rc.4** on `fix/october-audit-release`; hosted CI and publication pending |
| Historical stable tag | [v0.1.1](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.1.1); also predates the October fixes |
| rc.3 source archive | Sanitized replacement prepared; upload and published checksum verification pending |
| Supported execution | Local and CI; the [project page](https://ahines99.github.io/portco-data-onboarding/) is a static replay |

## What changed

The [October audit](AUDIT-2026-10-10.md) found 23 numbered defects, including a revenue classification that produced zero revenue while every check passed. The [remediation ledger](REMEDIATION-2026-10-11.md) maps fixes to regression tests. The follow-up also fixes shared workflow-cache races, forwards cancellation into worker loops and terminates cancelled dbt processes.

Distribution rules now exclude local `/.config/` data. The prepared rc.3 correction removes only `.config/auth0/config.json` from the original archive; it does not retag or substitute new application code. All 429 retained archive entries were verified unchanged. The original file held development metadata, not tokens or secrets.

Frozen audit evidence retains its original bytes. Fresh Git commit/clone tests check all 33 manifest hashes with and without automatic line-ending conversion.

## Verification

Release verification must identify the exact source commit and successful hosted CI run. Local checks cover lint/types, Python regressions, golden evaluations, frozen benchmark safety, Auth0 Actions, package installation and the scripted demo. PostgreSQL, container runtime restrictions, non-default container `PORT`, production entry-point startup/restart and fresh vulnerability scans require the hosted jobs before this candidate can ship.

The refreshed scripted demo is recorded after the implementation commit and identifies that commit in [its provenance](evidence/demo-replay.json). It has 28 review items and 27/27 reconciliation checks. Reviewer decisions are scripted; this is not a human usability study.

## Scope and limitations

Supported inputs are synthetic fixtures, explicit [CSV snapshots](CSV-SOURCE.md) and bounded read-only [PostgreSQL snapshots](POSTGRES-SOURCE.md). Certification applies to the reviewed source, relationships, transforms and supported metrics. Unknown semantics remain review work.

The frozen v1 and v2 safety results are post-remediation observations, not fresh independent validation. The earlier 0/10 probe, remaining incorrect proposals and other constraints are explained in [evaluation and limitations](EVALUATION.md). Full MetricFlow support, independent usability, customer savings and accepted live hosting remain unclaimed. Container scan results may retain unfixed upstream vulnerabilities even when the fixable HIGH/CRITICAL gate passes.

Deferred engineering work: a fresh frozen source-family corpus, stateful workflow property testing, reconciliation streaming and memory measurements at the 250,000-row bound, and GL currency contracts.

## Reading path

[Project page](https://ahines99.github.io/portco-data-onboarding/) → [case study](portfolio_case_study.md) → [architecture](architecture.md) → [evaluation and limitations](EVALUATION.md) → release status.

Historical acceptance and planning are in [the archive](archive/README.md). Exact prior release checks and assets remain attached to their [GitHub releases](https://github.com/ahines99/portco-data-onboarding/releases).
