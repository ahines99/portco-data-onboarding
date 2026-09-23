# 3-minute demo script

**Setup (before recording).** Run `uv sync --all-extras` and `uv run poe fixtures` (fixtures are
pre-generated). Clear state with `rm -rf var/demo`. Use a terminal font of 16pt or larger, and keep
`docs/architecture.md` open in a second pane for the diagram.

| Time | Beat | On screen | Say |
|---|---|---|---|
| 0:00 | Problem | Architecture diagram | "A PE firm buys a company. Its data is unfamiliar, messy and full of PII. Onboarding it into the firm's reporting takes weeks of analyst time. This agent does the discovery and the modelling, but never the trusting." |
| 0:20 | Kickoff | `uv run poe demo` starts | "One command: a synthetic SaaS company with traps planted in its data." |
| 0:35 | Profiling and PII | "findings: …" line | "Profiling is aggregate-only. The model never sees a row. Ten PII columns were classified by counting pattern matches inside the database." |
| 0:55 | Traps caught | "trap caught" lines | "Invoice lines are in cents while invoices are in dollars, and a CRM column called `rev` is really bookings. Neither is guessed; both go to a human." |
| 1:15 | Separation of duties | "agent tried to approve … Forbidden" | "The agent cannot approve its own proposals. Only a reviewer principal can, and the approval is bound to a hash of exactly what was reviewed." |
| 1:35 | Sandbox and reconciliation | "17/17 reconciliation checks exact to the cent" | "Generated dbt runs against a disposable read-only copy. Billings, ARR and GL revenue are recomputed independently in Python and must match to the cent." |
| 2:00 | Certification and publish | "certified … published v0001" | "A human certifies the bundle and each metric. Publishing is idempotent and audited, and the audit log is hash-chained." |
| 2:20 | Failure path | Section 2 output | "Now a bad day: the source times out mid-profile, and it retries. The data has negative invoice lines, so dbt tests fail in the sandbox, downstream marts are skipped, and the run stops for review. Nothing publishes." |
| 2:45 | Evidence | `var/demo/success_report.md` | "Every finding cites evidence ids down to the source reads. 34 golden eval cases gate CI." |
| 2:55 | Close | README heading | "That is why this is not just a chatbot." |

**Backup if something fails live:** show `evals/reports/latest.md` and the committed run report
from a previous `poe demo`.
