# From ambiguous source data to reviewable financial metrics

**Alex Hines · Python / SQL / dbt / DuckDB / PostgreSQL / MCP**

[Project page](https://ahines99.github.io/portco-data-onboarding/) → **Case study** →
[Architecture](architecture.md) → [Evaluation and limitations](EVALUATION.md) →
[Release status](RELEASE-STATUS.md)

## The problem

A company's schema does not automatically share an investor's reporting definitions. One source
stores invoice lines in cents and headers in dollars. Another labels potential CRM bookings `rev`.
Matching familiar names can produce a financially wrong answer that still looks reasonable.

This prototype turns that ambiguity into a reviewable workflow. It profiles metadata and aggregates,
proposes evidence-linked mappings, generates dbt and semantic definitions, reconciles the results,
and waits for a separate reviewer to certify the exact bundle before publication. The complete
financial demonstration uses synthetic SaaS and SAP-style sources.

## My role

I chose this project to explore how AI-assisted onboarding can remain auditable when definitions,
units and schemas disagree. My role included setting the portfolio direction, reviewing
recommendations and deciding which capabilities to pursue. I used AI coding tools extensively
for implementation, tests, audits and documentation. I distinguish what the prototype demonstrates
from what still needs external validation; automated reviewer identities are not a human usability study.

## The engineering decisions

| Decision | Reason |
|---|---|
| Persist state outside the conversation | Runs need to survive interrupted clients, reviewer waiting and service restarts. |
| Give agents typed MCP capabilities | Explicit principal and tenant checks constrain each action. |
| Calculate financial values in code | Generated SQL must reconcile with independent reference calculations. |
| Bind approval to content | A changed mapping or artifact cannot inherit an earlier decision. |
| Separate mapping review from certification | Source interpretation and approval of the tested result are distinct decisions. |
| Recover publication across two stores | Filesystem rename and database commit can fail separately; retries must verify exact files. |
| Restrict profiling to aggregates and approved domains | A seemingly harmless category can still contain personal information. |

The [architecture](architecture.md) and its decision records explain the mechanisms and trust boundaries.

## The audit that changed the correctness model

In October 2026, a ten-agent audit recorded 23 findings. Its most consequential financial
reproduction passed a real generated dbt build and every reconciliation check while turning
a 100.00 revenue credit into zero recognized revenue. The source category was `Revenue`;
both calculators expected lowercase canonical categories and silently omitted it.

The lesson was specific: independent arithmetic does not ensure independent semantic validation.
The repair gives canonical categories executable constraints. Unknown or null classifications
withhold affected metrics; case and whitespace normalization require an explicit reviewed transform.
An independent domain check can now fail even when the monetary calculations agree.

The same audit found rejected relationships returning in generated SQL, cached generation skipping
revoked authority and a stale worker adopting its successor's lease. The
[remediation record](REMEDIATION-2026-10-11.md) connects those fixes to regression tests at the
reproduced boundaries. The [audit, probes and results](AUDIT-2026-10-10.md) preserve the earlier failures.
[Release status](RELEASE-STATUS.md) separates implementation from exact-source CI and release verification.

## What the evidence supports

The SaaS demo publishes nine reconciled metrics after scripted separate-reviewer decisions.
A separate source-informed agent review published six supported SAP-style metrics and explicitly
rejected a misleading status mapping. Typed CSV and read-only PostgreSQL extraction have synthetic
end-to-end verification. A 10,000-row real historical retail exercise demonstrates ingestion and
profiling only.

Unfamiliar schemas expose the limits. The original probe matched 0/10 targets. Later frozen
agent-authored corpora preserved failed safety gates; remediation increased review coverage,
leaving wrong proposals and substantial reviewer effort. These are useful regression experiments,
not proof of arbitrary-schema accuracy or independent human validation.

Start with the [replay and transcript](index.html#demo), then use
[evaluation and limitations](EVALUATION.md) for the complete result populations and evidence links.
The workflow publishes locally. No live backend, customer outcome, analyst-time savings or
independent human usability result is claimed.

## Questions this project lets me examine

How does a cent become a dollar without rounding away evidence? Why can two agreeing calculators
both be wrong? What happens when an approval expires during a retry? How do you recover after a
directory rename succeeds but its database transaction fails? What does a perfect fixture score
leave untested?

Those questions guide the implementation and its regression tests. The public reading path ends
with [release status](RELEASE-STATUS.md), where each verification claim is tied to a revision.
