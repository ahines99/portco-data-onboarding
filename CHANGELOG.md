# Changelog

## 0.2.0rc1 ? live-service deployment candidate

- Add strict RS256 JWT verification with issuer/audience/tenant enforcement and rotation-aware JWKS caching.
- Reject unsafe production configuration, local identity fallback and unauthenticated transport.
- Add schema/storage readiness, bounded HTTP sessions/workload, and a managed PostgreSQL cloud entry point.
- Prepare Render infrastructure and tested Auth0 login/machine entitlement actions.
- Keep live deployment and recovery acceptance explicitly pending; no live readiness claim.


## 0.1.1 ? final audit hardening

- Bind CLI and MCP review decisions to the caller-reviewed run, gate and content hash; validate against locked current state. Certification requires its dedicated route.
- Block invoice reconciliation on any header/line discrepancy, including a single cent in large invoice populations.
- Handle equivalent Windows extended-path spellings during concurrent publication without relaxing containment checks.
- Preserve owner-approved assistant annotation provenance when reproducing live-study scores.
- Align public scope and acceptance claims with the supported synthetic fixtures and recorded evidence.
- Fail CI on fixable high/critical image vulnerabilities while retaining the complete scan report.

Review clients must now supply `subject_hash` and `gate` to `submit_mapping_review`; stale review files must be re-exported.

## 0.1.0 — final portfolio release

- Persistent nine-step onboarding with three human review boundaries and typed MCP/CLI interfaces.
- Synthetic source fixtures, deterministic mapping, generated dbt and nine executable monthly metrics.
- Recovery-safe certified publication, lease fencing, exact artifact verification and chained audit events.
- All 19 findings from the September audit remediated with regression coverage.
- Isolated PostgreSQL test databases, persistent Compose data, base-only installed-package verification.
- MIT license, public evidence and portfolio documentation; six live model sessions, owner-approved annotations and delegated final acceptance recorded.

See [release status](docs/RELEASE-STATUS.md) for current verification and accepted scope limits.
