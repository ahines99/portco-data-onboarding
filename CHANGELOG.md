# Changelog

## 0.2.0rc4 — October audit remediation (2026-10-16)

- Address all 23 October audit findings, with regressions for reproduced defects. Noncanonical account types such as `Revenue` no longer silently produce certified zero revenue; unknown values require evidence, and normalization requires review.
- Enforce current approvals, rejected relationships, lease ownership and capability phase boundaries; recover verified publication after a crash without authorizing new side effects.
- Harden CSV/PostgreSQL ingestion, SQL scope checks, money precision, telemetry redaction, migrations, CLI exit codes and evaluation gates.
- Isolate per-workflow policy caches during concurrent runs. Forward client cancellation and shutdown to the worker loop, cancel explicit runs promptly and terminate interrupted dbt subprocesses.
- Add parallel-run and mid-run cancellation regressions, a production entry-point smoke job and a container check on a non-default `PORT`.
- Exclude local `/.config/` files from Git, source distributions, wheels and Docker contexts. Preserve all 33 frozen October audit hashes across fresh Git checkouts.
- Refresh the demo to 28 review items and 27/27 reconciliation checks. Save diagnostics beside demo reports by default; `portco demo --verbose` displays them.
- Simplify the public documentation path, add the architecture diagram and audit story, archive process records and update release evidence after committing.

The rc.3 source archive requires a separate packaging-only replacement removing `.config/auth0/config.json`, which contained development metadata and no tokens. Its source tag and retained files remain unchanged. See [release status](docs/RELEASE-STATUS.md) for published verification and asset correction status.

## 0.2.0rc3 — automated qualification and PostgreSQL sources (2026-09-28)

- Add bounded, read-only PostgreSQL snapshots with explicit types and keys, privilege checks, consistent table locks and atomic registration.
- Exercise synthetic PostgreSQL extraction through nine-metric publication in CI.
- Record separate automated operator/reviewer qualification and a frozen six-case corpus, retaining the first failed safety result and post-remediation limits.
- Add stage-appropriate evidence links and clarify automated review provenance.

## 0.2.0rc2 — external snapshots and review safety (2026-09-28)

- Add typed CSV snapshot import, conservative structural inference and unfamiliar-schema review-safety gates.
- Record a public retail profiling exercise and preserve failed benchmark results.
- Harden the container and verify actual runtime restrictions; prepare an unexecuted operator pilot kit.

## 0.2.0rc1 — live-service deployment candidate (2026-09-28)

- Add strict RS256 JWT verification with issuer/audience/tenant enforcement and rotation-aware JWKS caching.
- Reject unsafe production configuration, local identity fallback and unauthenticated transport.
- Add schema/storage readiness, bounded HTTP sessions/workload and a managed PostgreSQL cloud entry point.
- Prepare Render infrastructure and tested Auth0 login/machine entitlement actions.
- Keep live deployment and recovery acceptance explicitly pending.

## 0.1.1 — final audit hardening (2026-09-28)

- Bind CLI and MCP review decisions to the caller-reviewed run, gate and content hash; certification requires its dedicated route.
- Block invoice reconciliation on any header/line discrepancy, including a single cent in large populations.
- Handle equivalent Windows extended paths during concurrent publication.
- Preserve annotation provenance, align scope claims and fail CI on fixable high/critical image vulnerabilities.

Review clients must supply `subject_hash` and `gate` to `submit_mapping_review`; stale review files must be re-exported.

## 0.1.0 — initial portfolio release (2026-09-27)

- Persistent nine-step onboarding with three review boundaries and typed MCP/CLI interfaces.
- Synthetic fixtures, deterministic mapping, generated dbt and nine executable monthly metrics.
- Recovery-safe certified publication, lease fencing, artifact verification and chained audit events.
- September audit regressions, isolated PostgreSQL tests, Compose persistence and installed-package verification.
- MIT license, public evidence, six model sessions and disclosed delegated acceptance.
