# Security and support scope

This is a synthetic-data portfolio demonstration, not a production financial reporting service.
Supported release scope is Python 3.12, local SQLite/PostgreSQL state, DuckDB fixture sources and
versioned local publication. Static bearer tokens and trusted local reviewer identities are for
development and must never be exposed publicly. The new deployment candidate adds strict JWT
authentication for an access-controlled synthetic live service; see [live acceptance prerequisites](docs/LIVE-DEPLOYMENT.md).
It has not yet been validated against a real hosting/identity account. Do not use real personal/company data.

For a sensitive vulnerability, use GitHub's private vulnerability reporting on the repository's
Security tab. Do not open a public issue containing credentials, source records or exploit data.
If private reporting is unavailable, contact the maintainer through the linked GitHub profile to
arrange a private channel; do not include sensitive details in the initial message.

Security checks are point-in-time evidence, not a guarantee. Dependency updates, changed model
versions, source integrations and deployment changes require renewed verification. The
[threat model](docs/threat_model.md) documents residual risks and the trusted operator boundary.
