# Inspectable evidence

These artifacts come from actual deterministic fixture runs. All reviewer decisions in this
directory are **automated synthetic test decisions**, not independent approvals by Alex or a live
model study. Private workspace prefixes are replaced in shareable outputs. The raw local state
remains outside Git. The manifest hashes the normalized shared files; it is not a signed audit export.

Start with [success](success-report.md), [controlled failure](failure-report.md),
[reconciliation](reconciliation.json), [certification](certification.json), and
[recovery verification](recovery.json). [Manifest](manifest.json) records source revision, dirty-state
flag, dependency versions, fixture/lock hashes and file digests. The replay has its own source revision
and timestamp because it is a separate actual run.

Reproduce with `uv run python -m scripts.release_evidence` and
`uv run python -m scripts.record_demo`. Both allocate fresh temporary runtime state rather than
resetting an existing user's run. They make no model API calls. A source revision with documentation
or evidence changes pending is explicitly marked dirty; do not interpret it as a pristine release build.
