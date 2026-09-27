# Contributing

Use Python 3.12 and `uv sync --all-extras --frozen`. Run `uv run poe fixtures`,
`uv run poe lint`, `uv run poe typecheck`, `uv run poe test` and `uv run poe eval`.
Contract changes also require `uv run poe schemas` and `uv run poe docs`.

Keep changes scoped. Include the problem, behavior change and relevant validation in a pull request.
Financial behavior needs an independent expected result; approval/security changes need a negative
test. Never include credentials, source company records, local databases or private transcripts.

PostgreSQL tests allocate their own database and require a disposable server with CREATE DATABASE
permission, `PORTCO_TEST_POSTGRES_URL`, and `PORTCO_TEST_POSTGRES_ALLOW_CREATE=1`.
Do not point these tests at a shared/production server. See [operations](docs/operations.md).

Fixture data is synthetic. New examples must remain synthetic or come with explicit redistribution
permission. This project is MIT licensed; third-party dependencies retain their own licenses.
