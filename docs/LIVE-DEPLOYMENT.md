# Live deployment: Render + Auth0

Status: **free portfolio delivery; backend not deployed**. On 2026-09-28, the owner chose
"Keep this project free" after reviewing the recurring hosting estimate. GitHub Pages remains
the public project page and recorded replay, with local execution for the full workflow.
No paid hosting or Auth0 upgrade is authorized. The paid recipe below is retained as an optional
future deployment path, not the current plan.

Render's free web service cannot attach the persistent disk this application uses for artifacts
and source snapshots, and free Render PostgreSQL expires after 30 days. It does not satisfy this
project's durable production acceptance criteria. See [Render free limits](https://render.com/docs/free).

The v0.2.0-rc.2 portfolio
prerelease is available. Render and Auth0 account access was verified on 2026-09-28. The custom
API, agent and reviewer application registrations, and both entitlement Actions are created.
A real Auth0 agent token passed the application's verifier using live JWKS; the wrong audience
was rejected. Reviewer login/MFA, spending authorization, billing setup and the live acceptance
checks below remain incomplete. These identity checks do not establish live service readiness.

Render's authenticated Blueprint validation found that `maxShutdownDelaySeconds` is unsupported
with a persistent disk; that setting has been removed. Validation now reports `need_payment_info`
for the app and database. No paid Render resources have been created. See the
[preflight record](evidence/cloud-preflight-20260928.json).

## Recommended first deployment

Use [render.yaml](../render.yaml): one 1 CPU / 2 GB application instance, PostgreSQL 16 on the
0.5 CPU / 1 GB plan with 5 GB database storage, and a 10 GB `/data` disk, all in Virginia.
Use the assigned `onrender.com` hostname initially. Keep the public portfolio on GitHub Pages.
Use Auth0 Essentials for reviewer MFA; its current B2C pricing lists $35/month and Pro MFA.
The free tier does not satisfy this guide's reviewer MFA requirement. Confirm the selected
tenant's MFA and machine-to-machine entitlements before purchasing; do not rely on trial features.
The first service contains only generated synthetic data; no source connector for customer data
is enabled by this deployment recipe. Machine clients are agents; human accounts hold reviewer access.

Published prices checked on 2026-09-28 total approximately **$83/month**: $25 for the app,
$19 for PostgreSQL compute, $1.50 for 5 GB database storage, $2.50 for the 10 GB persistent disk,
and $35 for Auth0 B2C Essentials. This assumes Render's free workspace plan and excludes taxes,
usage overages and temporary recovery-test resources. Auth0's published Essentials allowance is
1,000 machine-to-machine token requests per month; request tokens on demand and reuse them until
expiry instead of renewing continuously while idle. Confirm the actual account entitlements.
Use a provisional total budget of $100/month before tax and review the actual provider quote
before provisioning. This estimate is not authorization to spend. Avoid paid workspace upgrades,
custom-domain purchases and automatic storage scaling for the initial service. This is an estimate,
not a provider-enforced spending cap; monitor usage charges and configure available billing alerts.
[Current pricing](https://render.com/pricing), [Auth0 plans](https://auth0.com/pricing).

The persistent disk limits this design to one instance and causes brief deployment downtime.
It is appropriate for an access-controlled portfolio workload, not an HA service. Database and
artifact storage are separate, so their backups must be coordinated with writes stopped.
[Render disk constraints](https://render.com/docs/disks).

## Identity setup

1. Create an Auth0 tenant in the US and a custom API named `Portco Data Onboarding`, with identifier
   `https://portco-data-onboarding-api`, RS256 signing, and an access-token lifetime of 600 seconds.
   Do not use the Auth0 Management API audience. Disable public signup for the reviewer application.
2. Create a machine-to-machine agent application authorized only for this custom API. Set its
   administrator-controlled client metadata `portco_companies` to the JSON string `["portco_a"]`.
   Install and deploy [credentials-exchange.js](../deploy/auth0/credentials-exchange.js) in the
   Machine to Machine flow. It always issues `agent`, regardless of a client's requested role.
3. Create a separate Native application for an OAuth authorization-code/PKCE capable reviewer
   client. Add only that client's exact callback URLs. Assign the owner's human account
   administrator-controlled `app_metadata`:

   ```json
   {"portco_role": "reviewer", "portco_companies": ["portco_a"]}
   ```

   Install and deploy [post-login.js](../deploy/auth0/post-login.js) in the Login flow. It ignores
   user-editable metadata and refuses missing, wildcard or invalid entitlements. Enable MFA for the
   reviewer and administrative accounts. Never pass the reviewer's token to the autonomous agent.
4. Use a client that supports pre-registered OAuth clients with code/PKCE. Auth0 tenant/client setup
   and its callback URL must be verified with the actual selected client; dynamic registration is
   not assumed. This repository supplies a resource server, not an authorization server or login UI.

The verifier validates signatures, exact issuer, API audience, expiration, issued-at time, optional
not-before, token lifetime and explicit role/companies. Accepted tokens are RS256 access tokens with
`JWT` or `at+jwt` type and a key ID from the configured JWKS. Token-provided key URLs are rejected.
ID tokens have the client audience and must fail the API audience check. Each token expires within
one hour at most; the recommended issuer configuration uses ten minutes. Signing-key cache lifetime
is five minutes, with a 30-second unknown-key refresh cooldown. Prepublish replacement keys before
rotating. Revoking a user does not invalidate an already-issued JWT instantly: remove access, wait
for the short TTL, or stop the service during an incident. No instant token revocation is claimed.

References: [Auth0 custom claims](https://auth0.com/docs/secure/tokens/json-web-tokens/create-custom-claims),
[MCP authorization](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/authorization.md),
[PyJWT verifier](https://pyjwt.readthedocs.io/en/stable/api.html).

## Provision and start

Apply the Blueprint only after reviewing its named resources, actual price and permissions. Use a
new project/database, not an existing business database. Automatic deployment is disabled so a
green, explicitly selected commit can be deployed after backup and maintenance preparation.
The database has no external IP allowlist entries; only same-region internal networking is used.

Provide these values through Render's environment settings, never source control or chat:

| Setting | Value |
|---|---|
| `PORTCO_HTTP_BASE_URL` | Exact assigned public `https://...onrender.com` origin, without trailing slash |
| `PORTCO_JWT_ISSUER_URL` | Exact Auth0 issuer, normally `https://TENANT.REGION.auth0.com/` |
| `PORTCO_JWT_JWKS_URL` | That tenant's `https://TENANT.REGION.auth0.com/.well-known/jwks.json` |
| `PORTCO_JWT_AUDIENCE` | `https://portco-data-onboarding-api` (already in Blueprint) |
| `DATABASE_URL` | Render injects its internal database connection string |

Remove `PORTCO_HTTP_TOKENS` entirely: even an empty configured value is refused in JWT mode.
No Auth0 client secret or signing private key belongs in the resource server; it needs public JWKS
only. The agent client holds its own credential in an approved secret store.

`python -m src.serve` validates production settings, normalizes the managed database URL to psycopg,
requires database TLS, migrates state, optionally seeds only the two synthetic fixtures, and starts
one HTTP worker on `$PORT`. Render's private database endpoint uses `sslmode=require`; this enforces
encryption, not CA/hostname verification. Use `verify-full` with a trusted CA for deployments that
support it. [Render connection guidance](https://render.com/docs/postgresql-creating-connecting).

The Docker image runs as UID 10001. Verify `/data` is writable by that UID on the actual service;
do not switch the runtime to root to make a failed mount check pass. `/healthz` is liveness;
`/readyz` returns 503 unless the database schema is current and the state volume is writable with
at least 100 MiB free. Readiness returns no private diagnostics. Configure provider alerts for
unhealthy service, restart loops and disk growth; readiness is not an alert-delivery system.

Application code under `/app` stays root-owned; the image strips SUID/SGID bits. After deployment,
run `python -m src.runtime_evidence --assert-image` inside an operator session and save its JSON
with the provider image identity and source SHA. It checks non-root identity and the scoped
filesystem inventory and records capabilities, `NoNewPrivs`, process names, mount boundaries and
available cgroup v2 limits without reading tokens or process arguments. Review paths before sharing.
The stricter `--assert-compose` mode is for the local Compose CI environment; its zero capabilities,
no-new-privileges and resource limits must not be attributed to Render without actual evidence.
See the [collector scope and limitations](image-risk-assessment.md#collecting-measured-container-evidence).

Production rejects local identity fallback, unauthenticated transport, SQLite state, disabled
reviewer separation and fault injection. MCP admits only the configured Host/Origin, limits request
bodies to 256 KiB, sessions to 64 with ten-minute idle expiry, and expensive tool work to one
operation at a time. Busy work returns a retryable error. HTTP connection concurrency is bounded.
These are resource bounds, not a comprehensive internet DDoS service or per-user quota system.

## Live acceptance — record evidence before marking deployed

The [live smoke command](../scripts/smoke_live.py) uses access tokens from the local environment,
never command arguments, and writes a token-free result:

```text
uv run python -m scripts.smoke_live --base https://YOUR-SERVICE.onrender.com
```

Set `PORTCO_SMOKE_TOKEN` to an agent access token in the local shell first. The default smoke stops
at mapping review. An explicitly authorized `--complete-synthetic` run additionally requires
`PORTCO_SMOKE_REVIEWER_TOKEN` and labels its automated reviewer decisions in the output. It does
not restart services or prove backup recovery; those separate checks remain below.

- Verify HTTPS certificate, `/readyz` 200 and correct protected-resource metadata.
- Verify missing, expired and wrong-audience tokens return 401, a different tenant is denied,
  and the agent cannot approve a mapping or certify. Record statuses without tokens.
- Start `fixture:portco_a`, review the exact mapping packet with a separate reviewer identity,
  run reconciliation, certify the current manifest and publish nine metrics. Label any delegated
  synthetic smoke approval as automation; do not present it as independent human review.
- Use an operator session to verify audit-chain integrity and every published file hash.
- Restart/redeploy the same tested commit; prove the run, artifacts and receipt persist.
- Rehearse a quiesced database-plus-artifact backup and restore in an isolated deployment at the
  same `/data` path. Automatic independent database and disk snapshots alone are not proof of a
  consistent application recovery point. Record achieved recovery time and data-loss window.
  If CSV sources are registered, stop imports too and include `/data/sources` with its snapshot
  databases and registrations; verify source digests and connection resolution after restoration.
- Inspect the fresh image scan and decide on every residual HIGH/CRITICAL vulnerability before
  exposure. The image gate rejects fixable HIGH/CRITICAL findings; it does not certify unfixed ones
  harmless. Use the [per-CVE assessment](image-risk-assessment.md) to record actual runtime evidence;
  Compose privilege restrictions do not automatically apply to Render. Monitor resource use on
  the selected plan during the full synthetic run.
- Record service URL, deployed source SHA, CI run, image scan, test timestamp and rollback/restore
  evidence. Only then change this document's status to deployed. Never call a configuration file a
  successful deployment.

## Remaining boundary

The historical unfamiliar-schema probe remains 0/10; the separate
[frozen benchmark](../evals/unfamiliar/README.md) does not establish arbitrary-source accuracy.
Full MetricFlow is unsupported, and live business data needs a separate data/PII review and
least-privilege source access. The [CSV importer](CSV-SOURCE.md) provides a bounded operator-file
integration, not a live SaaS connector. Production authentication
does not change those product limitations. See [operations](operations.md) and
[security review](security-review.md) for recovery instructions and residual risks.
