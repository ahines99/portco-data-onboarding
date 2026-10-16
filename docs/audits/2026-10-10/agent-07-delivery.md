# Agent 7/10 — Delivery, deployment, operations, and supply chain audit

Audit date: 2026-10-10. Reviewed checkout HEAD e1f8e369 (parent verified exact hosted CI identity). Scope: Dockerfile, Compose, optional Render recipe, startup/readiness, Alembic, recovery guidance/rehearsal, packaging declarations, dependency lock, and CI. No tracked source changes, provisioning, account writes, or real credentials were used. Docker daemon unavailable locally; actual container behavior below is either source-reviewed or attributed to the parent's hosted-CI verification.

## Assessment

The current delivery story is credible for a free, locally executed synthetic portfolio application: frozen dependency installs, a Linux/Windows wheel gate, SQLite/PostgreSQL tests, container/restart/persistence smoke, runtime privilege evidence, and image/dependency scanning are present. The checked-in deployment documents explicitly identify the backend as not deployed and do not claim HA or coordinated hosted recovery. Those are appropriate scope limits, not reasons to purchase hosting.

One concrete migration-path defect was reproduced. Additional recommendations concern bounded failure handling and reproducible release evidence; they should be prioritized after core product correctness and before any future hosted deployment.

## DEL-01 — P2 confirmed: Direct Alembic commands fail on percent-encoded URLs and echo the URL into errors

**References:** `migrations/env.py:12-16`; `pyproject.toml` task `migrate`; `docker-compose.yml` migration command; `docs/operations.md:84-86`. The safer existing implementation is `src/workflows/facade.py:49-54`.

When the Alembic config has its default URL, `env.py` passes `get_settings().db_url` directly into `Config.set_main_option`. ConfigParser interprets percent signs. URL-encoded passwords such as `%40` and `%25`, and local SQLite paths containing `%`, therefore raise before migration. The exception interpolates the complete supplied URL, so an ordinary traceback also exposes the encoded password to logs. This affects the documented `uv run poe migrate` and direct Alembic entry points. The current Compose sample password does not trigger it; customized encoded passwords do. `src.serve` calls `facade.migrate`, which already doubles `%`, so that cloud startup path is not affected by this particular defect.

**Executed reproduction:** In a temporary directory, set `PORTCO_DATABASE_URL=sqlite:///.../state%encoded.db`, invoke `.venv/Scripts/python.exe -m alembic current`: exit 1, `ValueError: invalid interpolation syntax`. Call `facade.migrate` against the identical URL: success and database created. A second, network-free reproduction invoked `alembic upgrade head --sql` with an entirely synthetic PostgreSQL password containing `%40` and `%25`: exit 1, interpolation error true, synthetic password present in exception true. Temporary SQLite state was removed by the standard temporary-directory context; no retained project state changed.

**Fix:** Apply the same `url.replace("%", "%%")` used in the facade at the `env.py` configuration boundary, or centralize URL injection so both paths use one implementation. Avoid echoing connection URLs in operator-facing failures.

**Regression test:** Run the actual Alembic CLI as a child process against a temp SQLite percent path and verify upgrade/current succeed. Add a network-free PostgreSQL `--sql` case with encoded dummy credentials, asserting the sentinel password is not emitted on failure. Existing facade-only percent handling tests do not cover this path.

**Primary source:** [Alembic Config.set_main_option](https://alembic.sqlalchemy.org/en/latest/api/config.html#alembic.config.Config.set_main_option) documents ConfigParser interpolation and escaping raw percent signs.

## DEL-02 — P2 operational improvement before hosting: Bound migration and readiness database work

**References:** `migrations/env.py:31-38`, `src/serve.py:35`, `src/adapters/db.py:200`, `src/readiness.py:19-20`, `src/mcp_server.py:87-95`, `Dockerfile:33`.

The normal PostgreSQL engine has a 5-second connection timeout and 5-second pool timeout. The separate migration engine created with `engine_from_config` has neither configured, so startup migration does not inherit those bounds. Neither engine configures a statement/lock timeout. The readiness SELECT can wait on an exclusive schema lock or stalled database; moving it to an AnyIO worker thread protects the event loop but does not place a deadline on the database operation. The Docker probe abandons its client request after three seconds; that does not itself cancel the server-side database call. Repeated blocked probes can retain workers/connections and make recovery noisier.

This is a source-supported failure-mode risk, not an observed production outage or an assertion that healthy readiness is slow. No hosted backend exists, and no database/network fault was injected into retained state. Do not rank it as a current internet incident.

**Fix:** Configure explicit connection and lock deadlines for migration; use a separately budgeted readiness connection/query, ideally with a small concurrency cap or short-lived cached result so repeated probes cannot multiply work. Set PostgreSQL session/transaction statement and lock timeouts for the specific operation, not globally for every database client. Match the entire readiness deadline to the Docker/provider probe budget. An HTTP timeout alone is insufficient if the thread's synchronous query continues indefinitely.

**Test plan:** With an isolated PostgreSQL CI database, hold an exclusive lock on `alembic_version` and verify `/readyz` returns 503 within the selected budget, `/healthz` still succeeds, and repeated checks do not accumulate checked-out connections. Separately exercise connection refusal and migration lock contention. Release the test lock and confirm readiness recovers without restarting the app.

**Primary sources:** [PostgreSQL 16 statement_timeout and lock_timeout](https://www.postgresql.org/docs/16/runtime-config-client.html) document zero/default as disabled; [libpq connection parameters](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-PARAMKEYWORDS) document missing connect_timeout as unbounded; [Render health checks](https://render.com/docs/health-checks) require an HTTP response within five seconds. The accumulating-worker impact is an inference from these documented semantics and this code.

## DEL-03 — P3 supply-chain/release improvement: Preserve exact build identity

**References:** `Dockerfile:3-4,18`, `.github/workflows/ci.yml:24-25,31,143-145,168,174`, `render.yaml:6,11`.

The Python lock contains versioned artifacts and hashes and CI uses `--frozen`, which is good. However, Python base images, uv image, PostgreSQL image, scanner image, and Actions still use mutable tags. The CI image is built and scanned locally; the optional Render Docker recipe rebuilds from source. Therefore an identical application commit does not guarantee the same OS/build-tool bytes or the exact image that passed CI. This is a reproducibility/trust gap rather than evidence of compromise. Current read-only workflow permissions and lack of deployment secrets reduce consequence.

**Fix:** Pin Actions to verified full SHAs with version comments and image inputs to digests, and use an automated reviewed update cadence so pinning does not freeze security updates. Record source SHA, uv/build backend version, wheel SHA256, image digest, SBOM, and scan timestamps together. If paid hosting is later authorized, promote the tested image digest or rescan the actual provider image rather than treating a same-commit rebuild as identical evidence. Add a modest scheduled/manual dependency and container refresh while the portfolio is idle; current CI runs on push, PR, or dispatch only. An old green scan is historical evidence, not a current vulnerability assessment.

**Primary sources:** [GitHub secure use of Actions](https://docs.github.com/en/actions/reference/security/secure-use) explains full-SHA action pinning; [uv Docker integration and provenance](https://docs.astral.sh/uv/guides/integration/docker/) describes exact image/digest verification. Keep the automation free within the existing owner-approved scope.

## DEL-04 — P3 validation gap: Exercise the actual production entry point locally in CI

**References:** `Dockerfile:34`, `docker-compose.yml`, `.github/workflows/ci.yml:140-185`, `render.yaml:11`, `src/serve.py:32-49`, `tests/test_production_runtime.py`.

The container smoke runs the default uvicorn/static-token Compose configuration, while the Render recipe runs `python -m src.serve` with production JWT settings, startup migration, managed URL normalization, optional seed generation, and connection bounds. Unit tests cover readiness and URL preparation, and other security suites cover JWT independently, but the inspected CI does not boot that full production entry-point combination. This does not invalidate the local delivery gate; it limits what a green container job establishes about the optional deployment.

**Fix/test:** Add a free CI production-profile smoke with isolated Postgres, generated test signing keys, a local test JWKS HTTPS endpoint, a temporary `/data`, and a non-default `PORT`. Verify startup/migration, correct host/origin handling, readiness, JWT access and wrong audience, graceful termination, persistence and restart. Test the image as UID 10001. Continue to keep actual Render/Auth0 MFA, provider isolation, and coordinated database-plus-disk restoration as explicitly unverified external acceptance items.

A small related configuration inconsistency exists at `Dockerfile:33-34`: default Docker health checks honor `PORT`, but default uvicorn is fixed to 8000. Setting `PORT` on the default image without also overriding its command produces a false unhealthy state. The current Compose default and Render command override avoid it. Either keep both fixed for the default image or use a common configurable entry point and add a non-default-port smoke.

## Recovery and capacity observations

- The operations guide correctly requires quiescing workflow writes and CSV imports, preserving the state DB plus artifacts/publications/sources/config, and restoring the same path because receipts bind absolute paths. Do not promise relocatable restores or HA without changing that contract.
- `scripts/release_evidence.py` is an isolated SQLite rehearsal. It does not establish achieved hosted PostgreSQL RTO/RPO. The live guide explicitly leaves a coordinated restore rehearsal open; preserve that distinction.
- Persistent disk growth has only a 100-MiB readiness threshold; automated retention or quotas are not present. For larger usage, first measure bytes/run, source-snapshot growth, and lease/sandbox cleanup before adding quotas. Keep certified immutable artifacts outside any broad cleanup routine.
- Single process and one expensive workflow at a time are deliberate safe limits for this project. Do not add Uvicorn workers or instances merely for benchmark throughput without revisiting the process-local limiter, shared storage, and lease semantics.

## Verification and limits

Executed `.venv/Scripts/python.exe -m pytest -q tests/test_production_runtime.py`: **4 passed in 1.01 seconds**. Executed two safe Alembic reproductions described above. Read operational and deployment source; browsed official Alembic, PostgreSQL, GitHub, uv, and Render guidance on 2026-10-10. No full test suite, wheel smoke, dependency scan, Docker rebuild, or account validation was duplicated: the parent owns those checks. Parent reports exact-HEAD hosted CI all ten jobs successful and current dependency audit 121 packages/zero known vulnerabilities, with own project skipped; these are parent-supplied facts, not independently rerun here.
